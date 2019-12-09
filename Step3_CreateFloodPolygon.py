''' Automates the creation of a water surface based on estimated wave height.
Subtracts DEM from water elevation to determine flooded area.
Parameter[0] Note - choosing the Dam.gdb as the workspace will run a single dam. Choosing a folder will run on all dams in the folder. 
'''
#Create points along river lines every x distance, starting at the dam location.
def addWSEPoints(spacing, damID, flowPath, WSE_FC, WSE2_FC):

    #Get dam height
    with arcpy.da.SearchCursor("dam"+damID, ["DamID", "Dam_height"]) as cursor:
        for row in cursor:
            if row[0]== damID:
                if row[1]=='' or row[1] == None:
                    return 0
                damHeight = float(row[1])
    del row, cursor

    #Create list of points to be created and add to WaveHtPts feature class
    for stream in arcpy.da.SearchCursor(flowPath, ["SHAPE@"]): 
        points = []
        length = int(stream[0].length)                  #units should be meters
        for i in xrange(0, length + spacing, spacing):  #add point every x meters
            point = stream[0].positionAlongLine(i)
            points.append(point)
        points.pop()
        arcpy.Append_management(points, WSE_FC, "NO_TEST")

        #Check where OBJECTID numbering starts for the newest points
        with arcpy.da.SearchCursor(WSE_FC, ["OBJECTID", "Dist_DS"]) as sCursor:
            for row in sCursor:
                if row[1] == None:
                    firstID = row[0]
                    break
        del row, sCursor

        #Calculate wave height given dam height and distance from dam
        with arcpy.da.UpdateCursor(WSE_FC, ["OBJECTID", "Dist_DS", "WaveHt"]) as cursor:
            for row in cursor:
                if row[0]>= firstID:
                    row[1]= (row[0]-firstID)*(spacing/1609.344) #Dist_DS in miles
                    row[2]=(0.5*damHeight)-(damHeight/40.0)*(row[1]) #WaveHt = WaveHt at dam - WaveHt Change per mile * Dist_DS in miles
                    cursor.updateRow(row)
        del row, cursor
    del stream

    #Get elevation at points. Calculate fields.
    ExtractValuesToPoints(WSE_FC, dem, WSE2_FC)
    arcpy.CalculateField_management(WSE2_FC, "WaveElev", "[RASTERVALU] + [WaveHt]")
    arcpy.CalculateField_management(WSE2_FC, "TSValue", "[RASTERVALU] + [WaveHt]")
    
    return damHeight


#Add Upstream WSE Points
def add_US_WSEPoints(spacing, damID, flowPath, flowPath_us, WSE2_FC):

    #Get dam height
    with arcpy.da.SearchCursor("dam"+damID, ["DamID", "Dam_height"]) as cursor:
        for row in cursor:
            if row[0]== damID:
                damHeight = float(row[1])
    del row, cursor

    #Create Upstream points
    with arcpy.da.UpdateCursor(flowPath_us, ["SHAPE@", "FROM_WSE", "TO_WSE"]) as streamCursor:
        for stream in streamCursor:
            points = []
            length = int(stream[0].length)                      #units should be meters
            for i in xrange(0, length + spacing, spacing):      #add point every x meters
                point = stream[0].positionAlongLine(length-i)   #start at DS end of stream
                points.append(point)
            xy = [points[0].getPart().X, points[0].getPart().Y] #coordinates for DS end of stream

            #Remove first and last point along flowPath_us
            points.pop()
            if len(points)>0:            
                points.pop(0)

            #Find the WSE value of the flowPath point closest to the DS end of flowPath_us.
            closeDist = 8000  #random large distance value
            with arcpy.da.SearchCursor(WSE2_FC, ["OBJECTID", "WaveElev", "SHAPE@"]) as cursor:
                for row in cursor:
                    WSE_XY = [row[2].getPart().X, row[2].getPart().Y]
                    distance = hypot(xy[0]-WSE_XY[0], xy[1]-WSE_XY[1])
                    if distance<closeDist:
                        closeDist = distance
                        WSE_Value = row[1]                    
            del row, cursor

            #Create the points
            if len(points)>0:
                arcpy.Append_management(points, WSE2_FC, "NO_TEST") 

                #Check where OBJECTID numbering starts for the newest points
                with arcpy.da.SearchCursor(WSE2_FC, ["OBJECTID", "WaveElev"]) as sCursor:
                    for row in sCursor:
                        if row[1] == None:
                            firstID = row[0]
                            break
                del row, sCursor

                #Calculate Wave Elevation as decreasing the farther you go upstream
                with arcpy.da.UpdateCursor(WSE2_FC, ["OBJECTID", "WaveElev", "TSVALUE"]) as cursor:
                    for row in cursor:
                        if row[0]>= firstID:
                            #WSE = WSE at flowPath - (WaveHt Change per mile)(Dist_DS in miles)...(The '+ 1' adds distance for the missing first point)
                            row[1]= WSE_Value - (damHeight/40.0)*Float(row[0]-firstID+1)*(spacing/1609.344)
                            row[2]= WSE_Value - (damHeight/40.0)*Float(row[0]-firstID+1)*(spacing/1609.344)
                            cursor.updateRow(row)
                del row, cursor

            #Fill in TO_WSE/FROM_WSE for flowPath_us
            stream[2] = WSE_Value
            #WSE at US end of tributary = WSE - WaveHt Change per mile * Length in miles
            stream[1] = WSE_Value - (damHeight/40.0)*(stream[0].length/1609.344)
            streamCursor.updateRow(stream)
        
    del stream, streamCursor
    

#Run Arc Hydro Tools to get flooded area.
def getFloodPolygon(workspace, flowPath, in_pts, out_pts, dem):
    arcpy.MakeFeatureLayer_management(out_pts, "WaveHtPts2")
    ArcHydroTools.AssignHydroID("WaveHtPts2")

    #Populate time series table. Setting a single time will apply the WSE to all points at once.
    arcpy.env.workspace = workspace
    with arcpy.da.SearchCursor(out_pts, ['HydroID', 'WaveElev']) as sCursor:
        with arcpy.da.InsertCursor("TIMESERIES", ['FeatureID', 'TSTime', 'TSValue']) as iCursor:
            for row in sCursor:
                iCursor.insertRow([row[0],"11/11/2016 12:00:00 AM", row[1]])
    del row, sCursor, iCursor

    #Stream WSE from Point WSE (creates a rasterized line)
    #Define Variables
    flowPath_us = os.path.join(workspace, "flowPath_us")
    Line3D_us = os.path.join(workspace, "Line3D_us")
    Line3D = os.path.join(workspace, "Line3D")
    LineRaster = os.path.join(workspace, "LineRaster")
    TIMESERIES = os.path.join(workspace, "TIMESERIES")
    parentFolder = os.path.dirname(workspace)

    #Create 3D Lines
    arcpy.AddMessage("...creating 3D lines...")
    ArcHydroTools.UpdateTSValueonPoints(out_pts, TIMESERIES, 1, "11/11/2016 12:00:00 AM")
    ArcHydroTools.PointTSValueto3DLine(out_pts, flowPath, dem, Line3D, "None", "No")
    arcpy.FeatureTo3DByAttribute_3d(flowPath_us, Line3D_us, "FROM_WSE", "TO_WSE")
    arcpy.Append_management(Line3D_us, Line3D, "NO_TEST") 

    #Convert 3D Lines to Raster
    arcpy.AddMessage("...converting line to raster...")
    try:
        ArcHydroTools.Convert3DLineToRaster(dem, Line3D, LineRaster)
        arcpy.env.workspace = workspace
        outSetNull = SetNull(LineRaster, LineRaster, "VALUE=0") #Set zeroes to NULL

        #Flood from stream WSE
        arcpy.AddMessage("...extrapolating out water surface...")
        arcpy.Append_management(flowPath_us, flowPath, "NO_TEST") 
        ArcHydroTools.FloodFromStreamWSEPy(outSetNull, dem, parentFolder, "Layers", flowPath)
        return True
    except:
        return False

#Copy flooding polygon so it doesn't get overwritten
def saveFloodPolygon(workspace, damID, outWorkspace):
    fpPath = os.path.join(os.path.dirname(workspace), r"Layers\Layers.gdb\Layers\FPPolyLayers")
    if arcpy.Exists(fpPath):
        arcpy.Copy_management(fpPath, os.path.join(outWorkspace, damID + "_Raw"))
        arcpy.Copy_management(fpPath, os.path.join(outWorkspace, damID + "_Final"))
    wsePath = os.path.join(os.path.dirname(workspace), r"Layers\Layers\wselayers")
    if arcpy.Exists(wsePath):
        arcpy.CopyRaster_management(wsePath, os.path.join(workspace, "wselayers"))
    fdPath = os.path.join(os.path.dirname(workspace), r"Layers\Layers\fdlayers")
    if arcpy.Exists(fdPath):
        arcpy.CopyRaster_management(fdPath, os.path.join(workspace, "fdlayers"))
    
#Clean up flowPath fc, clip to 5 miles
def clipFlowPath(workspace, flowPath, splitPt, flowPath1):
    #Use Surface_area to pick downstream distance
    damID = os.path.basename(workspace).split('.')[0]
    with arcpy.da.SearchCursor("dam"+damID, ["Surface_area"]) as damCursor:
        for row in damCursor:
            damSA = row[0]
    del row, damCursor

    distDS = {2: 3218.688, 5: 8046.72, 10: 16093.44}
    if damSA >= 25 and damSA < 100 or damSA==None or damSA=='':
        lenDS = distDS[5]  #5 miles in meters
    elif damSA < 25:
        lenDS = distDS[2]  #2 miles in meters
    else:
        lenDS = distDS[10]  #10 miles in meters
    
    for flowLine in arcpy.da.SearchCursor(flowPath, ["OBJECTID", "SHAPE@"]): 
        if flowLine[0]==1 and int(flowLine[1].length)>lenDS:
            point = flowLine[1].positionAlongLine(lenDS)
            arcpy.CreateFeatureclass_management(workspace, "splitPt", "POINT", "", "", "", flowPath)
            arcpy.Append_management(point, splitPt, "NO_TEST")
            arcpy.SplitLineAtPoint_management(flowPath, splitPt, flowPath1)
    del flowLine

    #Limit main flow path to 5 miles
    if arcpy.Exists(splitPt):
        arcpy.Delete_management(flowPath)
        arcpy.MakeFeatureLayer_management(flowPath1, "flowPath1")
        arcpy.SelectLayerByAttribute_management("flowPath1", "", ' "OBJECTID" = 1 ')
        arcpy.CopyFeatures_management("flowPath1", flowPath)
        arcpy.Delete_management("flowPath1")
    else:
        arcpy.MakeFeatureLayer_management(flowPath, "flowPath_lyr")
        arcpy.SelectLayerByAttribute_management("flowPath_lyr", "", ' "OBJECTID" = 1 ')
        arcpy.CopyFeatures_management("flowPath_lyr", "flowPath1")
        arcpy.Delete_management("flowPath")
        arcpy.CopyFeatures_management("flowPath1", "flowPath")
        arcpy.Delete_management("flowPath1")

#Clear MXD
def delLayers(delList):
    for lyr in delList:
        if arcpy.Exists(lyr):
            arcpy.Delete_management(lyr)
 
#---------------------------------------------------------------------------------
import arcpy, ArcHydroTools, os, sys
from arcpy import env
from math import hypot
from arcpy.sa import *
workingFolder = arcpy.GetParameterAsText(0)         #set GDB or folder containing GDB(s)
outWorkspace = arcpy.GetParameterAsText(1)          #GDB where resulting flood polygon will be saved
spacing = int(arcpy.GetParameterAsText(2))          #set point spacing, smaller spacing gives more detail
dem = "clipDEM"

arcpy.env.workspace = workingFolder
arcpy.env.overwriteOutput = True

#Works on a single dam GDB
if workingFolder.endswith(".gdb"):
    damID = os.path.basename(workingFolder).split('.')[0]
    arcpy.AddMessage("Starting dam " + str(damID))
    flowPath = os.path.join(workingFolder, "flowPath")
    flowPath1 = os.path.join(workingFolder, "flowPath1")
    flowPath_us = os.path.join(workingFolder, "flowPath_us")
    splitPt = os.path.join(workingFolder, "splitPt")
    dem = os.path.join(workingFolder, "clipDEM")
    damHeight = addWSEPoints(spacing, damID, flowPath, 'WaveHtPts', "WaveHtPts2")
    if damHeight == 0:
        arcpy.AddWarning("%s height = 0" %(damID))
        pass
    else:
        add_US_WSEPoints(100, damID, flowPath, flowPath_us, "WaveHtPts2")
        success = getFloodPolygon(workingFolder, flowPath, "WaveHtPts", "WaveHtPts2", dem)
        if success:
            saveFloodPolygon(workingFolder, damID, outWorkspace)
            clipFlowPath(workingFolder, flowPath, splitPt, flowPath1)            
        else:
            arcpy.AddWarning("%s Memory Error" %(damID))
        delLayers(["WaveHtPts2", "Line3D", "Line3D", "Line3D_us", "Line3D_us", "LineRaster", "LineToGrid", "splitPt", "outSetNull", "flowPath1"])
        fpGDB = os.path.join(os.path.dirname(workingFolder), "Layers\Layers.gdb")
        delLayers([fpGDB, os.path.dirname(fpGDB)])

#Works on multiple dam GDBs
else: 
    for gdb in arcpy.ListWorkspaces():
        if gdb.endswith(".gdb") and arcpy.Exists(os.path.join(gdb, "splitStreams")):
            arcpy.env.workspace = gdb
            damID = os.path.basename(gdb).split('.')[0]
            arcpy.AddMessage("Starting dam " + str(damID))
            flowPath = os.path.join(gdb, "flowPath")
            flowPath1 = os.path.join(gdb, "flowPath1")
            flowPath_us = os.path.join(gdb, "flowPath_us")
            splitPt = os.path.join(gdb, "splitPt")
            dem = os.path.join(gdb, "clipDEM")
            damHeight = addWSEPoints(spacing, damID, flowPath, 'WaveHtPts', "WaveHtPts2")
            if damHeight == 0:
                arcpy.AddWarning("%s height = 0" %(damID))
                pass
            else:
                add_US_WSEPoints(100, damID, flowPath, flowPath_us, "WaveHtPts2")
                success = getFloodPolygon(gdb, flowPath, "WaveHtPts", "WaveHtPts2", dem)
                if success:
                    saveFloodPolygon(gdb, damID, outWorkspace)
                    clipFlowPath(gdb, flowPath, splitPt, flowPath1)
                else:
                    arcpy.AddWarning("%s Memory Error" %(damID))
                delLayers(["WaveHtPts2", "Line3D", "Line3D", "Line3D_us", "Line3D_us", "LineRaster", "LineToGrid", "splitPt", "outSetNull", "flowPath1"])
                fpGDB = os.path.join(os.path.dirname(gdb), "Layers\Layers.gdb")
                delLayers([fpGDB, os.path.dirname(fpGDB)])


