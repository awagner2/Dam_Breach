'''Geodatabase Setup Tool
Prep: Create MXD with coordinate system that matches all of the input data.
    Display in meters will mean geoprocessing uses meters for the horizontal unit. Create an attribute 'DamID' for naming geodatabases.
    Have available the hydrology and DEM for surrounding counties as needed to cover the 2, 5, or 10 miles downstream of the dams.
    Copy the GenericCounty folder and rename to match the county name. Also rename the geodatabase in the same manner.
Process: Uses the AllDams feature class to identify dams in the specified county. Creates a GDB for each dam with the
    necessary layers, including hydrology features and a DEM that covers the required distance downstream.
'''

#Get streams within county (all line features)
def copyStreamLines(gdb, hydroGDB):
    arcpy.env.workspace = hydroGDB
    fcs = []
    for fds in arcpy.ListDatasets('','feature') + ['']:
        for fc in arcpy.ListFeatureClasses('','',fds):
            desc = arcpy.Describe(fc)
            type = desc.shapeType
            if type == "Polyline":
                fcs.append(os.path.join(hydroGDB, fds, fc))
    arcpy.env.workspace = gdb
    fcCount=len(fcs)
    if fcCount>0:
        if arcpy.Exists("countyStreams")==False:
            arcpy.CreateFeatureclass_management(gdb, "countyStreams", "Polyline", fcs[0], "", "SAME_AS_TEMPLATE", "damLyr")
        for i in range(fcCount):
            arcpy.Append_management(fcs[i], "countyStreams", "NO_TEST")

def getLayers(damWorkspace, damID, distText, demFolder, hydFolder):
    matchcount = int(arcpy.GetCount_management('countyLyr')[0])
    arcpy.Buffer_analysis(currentDam, "buffer"+damID, distText)

    #Bring in DEM(s) and countyStream(s)
    if matchcount>1:
        countyLyr = arcpy.MakeFeatureLayer_management("countyLyr", "neededCounties")
        demCount=1
        demList=[]
        with arcpy.da.SearchCursor("neededCounties", ["CNTYNAME"]) as rows:
            for row in rows:
                demGDB = os.path.join(demFolder, row[0]+".gdb")
                if arcpy.Exists(demGDB):
                    clipDEM(damWorkspace, demGDB, os.path.join(damWorkspace, "buffer"+damID), demCount)  #clip DEM(s)
                    demList.append("clipDEM"+str(demCount))
                    demCount+=1
                hydroGDB = os.path.join(hydFolder, row[0]+"HYD.gdb")
                if row[0]!= county and arcpy.Exists(hydroGDB):
                    copyStreamLines(damWorkspace, hydroGDB)         #append streams
        del row, rows
        if demCount>1:
            arcpy.MosaicToNewRaster_management(";".join(demList), damWorkspace, "clipDEM", "#", "32_BIT_FLOAT", "#", 1)
        elif demCount == 1:
            arcpy.CopyRaster_management("clipDEM1", "clipDEM")      #mosaic multiple DEMs
    else:
        demGDB = os.path.join(demFolder, county+".gdb")
        if arcpy.Exists(demGDB):
            clipDEM(damWorkspace, demGDB, os.path.join(damWorkspace, "buffer"+damID), 0)

    #Clip streams
    arcpy.Clip_analysis("countyStreams", "buffer"+damID, "clipStreams")
    arcpy.Intersect_analysis("clipStreams", "intersect", "ALL", "", "POINT")
    arcpy.UnsplitLine_management("clipStreams", "unSplitStreams", "", "")
    arcpy.SplitLineAtPoint_management("unSplitStreams", "intersect", "splitStreams", "0.1")
    arcpy.DeleteIdentical_management("splitStreams", "Shape")
    arcpy.MakeFeatureLayer_management ("splitStreams", "splitStreamsLyr")
                                        
    #Setup ArcHydro geometry on streams
    ArcHydroTools.AssignHydroID("splitStreamsLyr", "OVERWRITE_YES")
    ArcHydroTools.GenerateFNodeTNode("splitStreamsLyr")
    arcpy.env.workspace = damWorkspace
    ArcHydroTools.FindNextDownstreamLine("splitStreams")
    
#Clip DEM(s)
def clipDEM(damWorkspace, demGDB, clipFC, demCount):
    arcpy.env.workspace = demGDB
    currentDEM = arcpy.ListRasters("*")[0]
    if demCount>0:
        outDEM = os.path.join(damWorkspace, "clipDEM"+str(demCount))
    else:
        outDEM = os.path.join(damWorkspace, "clipDEM")
    arcpy.Clip_management(currentDEM, "#", outDEM, clipFC, "#", "NONE")
    arcpy.env.workspace = damWorkspace

#Clear MXD
def delLayers(gdb, delList):
    for lyr in delList:
        if arcpy.Exists(os.path.join(gdb, lyr)):
            arcpy.Delete_management(os.path.join(gdb, lyr))

#-----------------------------------------------------------
import arcpy, os, ArcHydroTools
from arcpy import env
from arcpy.sa import *
arcpy.env.overwriteOutput = True
arcpy.CheckOutExtension("3D")
arcpy.CheckOutExtension("Spatial")

#Identify County of Interest
gdb = arcpy.GetParameterAsText(0)           #set county.gdb location, e.g. C:\Project\Oconee.gdb
county = arcpy.GetParameterAsText(1)        #set county using dropdown
demFolder = arcpy.GetParameterAsText(2)     #folder containing DEM geodatabases (not the gdb itself)
hydFolder = arcpy.GetParameterAsText(3)     #folder containing hydrology geodatabases (not the gdb itself)
limitBy = arcpy.GetParameterAsText(4)       #list the dams to be include by DamID

arcpy.env.workspace = gdb
workingFolder = os.path.dirname(arcpy.env.workspace)
baseFolder = os.path.dirname(workingFolder)

#Get Features By County
arcpy.MakeFeatureLayer_management ("AllDams", "damLyr")
arcpy.SelectLayerByAttribute_management ("damLyr", "NEW_SELECTION",  '"Cnty_Name" = ' + "'%s'" %county)
arcpy.CopyFeatures_management("damLyr", "countyDams")

hydroGDB = os.path.join(hydFolder, county+"HYD.gdb")
copyStreamLines(gdb, hydroGDB)

#Set up GDB for each dam
damList, areaList = [], []

with arcpy.da.SearchCursor("countyDams", ["DamID", "Dam_height", "Surface_area"]) as rows:
    for row in rows:
        #if len(limitBy) == 0 and row[1] != None and row[2] != None:
        if len(limitBy) == 0:
            damList.append(row[0])
            SAValue=row[2]
            areaList.append(SAValue)
        else:
            #if row[0] in limitBy and row[0] != '' and row[1] != None and row[2] != None:
            if row[0] in limitBy and row[0] != '':
                damList.append(row[0])
                SAValue=row[2]
                areaList.append(SAValue)
    arcpy.AddMessage(damList)
del row, rows

for damID in damList:
    arcpy.AddMessage("Starting dam " + str(damID))
    damWorkspace = os.path.join(workingFolder, damID + ".gdb")
    arcpy.Copy_management(gdb, damWorkspace)
    arcpy.env.workspace = damWorkspace

    #Use surface area to pick distance downstream values
    damSA = areaList[damList.index(damID)]
    if damSA==None or damSA=='' or (damSA >= 25 and damSA < 100):
        distText = "5 Miles"
    elif damSA < 25:
        distText = "2 Miles"
    else:
        distText = "10 Miles"
    
    #Identify dam, check if other counties within x distance.
    currentDam = "dam" + damID
    arcpy.SelectLayerByAttribute_management ("damLyr", "NEW_SELECTION",  '"DamID" = ' + "'%s'" %damID)
    arcpy.CopyFeatures_management("damLyr", currentDam)
    arcpy.MakeFeatureLayer_management ("County", "countyLyr")
    arcpy.SelectLayerByLocation_management ("countyLyr", "WITHIN_A_DISTANCE", currentDam, distText)

    getLayers(damWorkspace, damID, distText, demFolder, hydFolder)
                                
    delList = ["AllDams", "buffer"+damID, "clipStreams", "County", "countyDams", "countyStreams", "unSplitStreams", "intersect", "clipDEM1", "clipDEM2", "clipDEM3"]
    delLayers(damWorkspace, delList)

