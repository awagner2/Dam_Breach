# ------------------------------------------------------------------------------
# Name: Create Flow Path
# Desc: Automates the ArcHydro tool: Trace feature by NextDownID attribute.
#     However, it does not handle flow splits at this time.
#     Parameter[0] Note - choosing a geodatabase as the workspace will run a single dam. Choosing a folder will run on all dams in the folder. 
# ------------------------------------------------------------------------------

#Get Hydro ID of first downstream line from dam point
def getDSHydroID(workspace, streamsFC):
    #Update ArcHydro geometry on streams in case edits were made.
    ArcHydroTools.GenerateFNodeTNode(streamsFC)
    arcpy.env.workspace = workspace
    ArcHydroTools.FindNextDownstreamLine(streamsFC)

    damID = os.path.basename(workspace).split('.')[0]
    xy=[]
    with arcpy.da.SearchCursor("dam"+damID, ["Shape@"]) as damCursor:
        for row in damCursor:
            xy = [row[0].getPart().X, row[0].getPart().Y]
    del row, damCursor
    with arcpy.da.SearchCursor("splitStreams", ["HYDROID", "NextDownID", "FROM_NODE", "Shape@"]) as streamCursor:
        for row in streamCursor:
            if row[3].firstPoint.X == xy[0] and row[3].firstPoint.Y == xy[1]:
                return (row[0], row[1], row[2])
    del row, streamCursor

#Query for features in a list
def queryStreams(streamsFC, streamList, selectType, selectField):
    q=[]
    for value in streamList:
        q.append(selectField+"="+str(value))
    query = " OR ".join(q)
    arcpy.SelectLayerByAttribute_management(streamsFC, selectType, query)
    
#Identify next downstream line from original stream. Does not check for flow splits.
def createMainFlowPath(workspace, streamsFC):       
    arcpy.MakeFeatureLayer_management (streamsFC, streamsFC)
    try:
        startID, NextDownID, startFromNode = getDSHydroID(workspace, streamsFC)
    except:
        damID = os.path.basename(workspace).split('.')[0]
        arcpy.AddWarning("%s downstream line not found. Try snapping or resetting NextDSID." %(damID))
        return False
    
    count=0
    dsList = [startID]
    fromList =[startFromNode]

    while NextDownID != -1 and count<50:
        with arcpy.da.SearchCursor(streamsFC, ["HYDROID", "NextDownID", "FROM_NODE"]) as rows:
            for row in rows:
                if row[0]== NextDownID:             
                    dsList.append(row[0])
                    fromList.append(row[2])
                    NextDownID=row[1]
                    count+=1
        del row, rows
    if -1 in dsList:
        listLoc = dsList.index(-1)
        dsList.remove(dsList[listLoc])
        fromList.remove(fromList[listLoc])

    #Create flowPath    
    queryStreams(streamsFC, dsList, "NEW_SELECTION", '\"HYDROID\"')
    arcpy.CopyFeatures_management(streamsFC, "flowPath_seg")
    arcpy.UnsplitLine_management("flowPath_seg", "flowPath", "", "")

    #Create upstream flowpath    
    queryStreams(streamsFC, fromList, "NEW_SELECTION", '\"TO_NODE\"')
    arcpy.SelectLayerByLocation_management (streamsFC, "SHARE_A_LINE_SEGMENT_WITH", "flowPath_seg", "#", "REMOVE_FROM_SELECTION")
    arcpy.CopyFeatures_management(streamsFC, "flowPath_us")
    arcpy.AddField_management("flowPath_us", "FROM_WSE", "DOUBLE")
    arcpy.AddField_management("flowPath_us", "TO_WSE", "DOUBLE")
    return True
    
#Check for errors
def checkFlowPath(workspace, flowPath, fpList):

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
    
    count = 0
    with arcpy.da.SearchCursor (flowPath, "SHAPE@") as cursor:
        for row in cursor:
            count+=1
            if count>1 or row[0].length<lenDS:
                fpList.append(os.path.basename(workspace).split('.')[0])
                break
    del row, cursor
    return fpList

#Clear MXD
def delLayers(delList):
    for lyr in delList:
        if arcpy.Exists(lyr):
            arcpy.Delete_management(lyr)

#---------------------------------------------------------------------
import arcpy, os, ArcHydroTools
from arcpy import env
from arcpy.sa import *

workingFolder = arcpy.GetParameterAsText(0)         #set GDB or folder containing GDB(s)
arcpy.env.workspace = workingFolder
arcpy.env.overwriteOutput = True

fpList = []
if workingFolder.endswith(".gdb") and arcpy.Exists(os.path.join(workingFolder, "splitStreams")):
    arcpy.AddMessage("Working on " + workingFolder)
    fpSuccess = createMainFlowPath(workingFolder, "splitStreams")
    if fpSuccess:
        fpList = checkFlowPath(workingFolder, "flowPath", fpList)
    delLayers(["splitStreams", "flowPath_seg", "flowPath_us_seg"])
else: 
    for gdb in arcpy.ListWorkspaces():
        if gdb.endswith(".gdb") and arcpy.Exists(os.path.join(gdb, "splitStreams")):
            arcpy.AddMessage("Working on " + gdb)
            arcpy.env.workspace=gdb
            fpSuccess = createMainFlowPath(gdb, "splitStreams")
            if fpSuccess:
                fpList = checkFlowPath(gdb, "flowPath", fpList)
            delLayers(["splitStreams", "flowPath_seg", "flowPath_us_seg"])

if len(fpList)>0:
    arcpy.AddWarning("The following flowPaths are shorter than 5 miles or contain multiple lines: " + ", ".join(fpList))
else:
    arcpy.AddMessage("Flow path set up complete.")
   
