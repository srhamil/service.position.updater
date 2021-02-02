'''
*  This work is licensed under the Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0) License.
*
*
*  To view a copy of this license, visit
*
*  English version: http://creativecommons.org/licenses/by-nc-sa/4.0/
*  German version:  http://creativecommons.org/licenses/by-nc-sa/4.0/deed.de
*
*  or send a letter to Creative Commons, 171 Second Street, Suite 300, San Francisco, California, 94105, USA.
'''


import xbmc
import xbmcaddon
import xbmcvfs
import socket
import json
import xml.etree.ElementTree as ET
import threading
from time import sleep
from time import time
from xml.dom import minidom
from os import path
import random
import traceback, sys
from datetime import datetime
from glob import glob





addon = xbmcaddon.Addon('service.position.updater')
addon_name = addon.getAddonInfo('name')
addon_icon = addon.getAddonInfo('icon')

delay = '4000'
logo = 'special://home/addons/service.position.updater/icon.png'

tracing = True

class ResumePositionUpdater():
    onStopAccuracy = 5
    monitor = xbmc.Monitor()

    def __init__(self):
        self.methodDict = {"Player.OnPause": self.OnPause,
                          "Player.OnPlay": self.OnPlay,
                          "Player.OnResume": self.OnResume,
                          "Player.OnSeek": self.OnSeek,
                          "Player.OnStop": self.OnStop,
                          "VideoLibrary.OnUpdate": self.OnUpdate,
                          "Player.OnAVStart": self.OnAVStart,
                          "Playlist.OnAdd": self.OnAdd,
                          "Playlist.OnClear": self.OnClear,
                          }

        self.playcountminimumpercent = self.GetKodiAdvancedSettingInt('playcountminimumpercent',90)
        self.ignoresecondsatstart = self.GetKodiAdvancedSettingInt('ignoresecondsatstart',180)
        self.ignorepercentatend = self.GetKodiAdvancedSettingInt('ignorepercentatend',8)
 

        self.XBMCIP = addon.getSetting('xbmcip')
        self.XBMCPORT = int(addon.getSetting('xbmcport'))
        
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setblocking(1)
        xbmc.sleep(int(delay))
        try:
            self.s.connect((self.XBMCIP, self.XBMCPORT))
        except Exception as e:
            xbmc.executebuiltin('Notification(%s, Error: %s, %s, %s)' % \
                                             (addon_name, str(e), delay, logo) )
            xbmc.sleep(int(delay))
            xbmc.executebuiltin('Notification(%s, Please check JSONRPC settings, %s, %s)' % \
                                              (addon_name, delay, logo) )
            xbmc.sleep(int(delay))
            exit(0)

 
    advancedSettingsFile='special://home/userdata/advancedsettings.xml'
    advancedSettingsFileProcessed = False
    advancedSettingsFileDom = None

    def LoadAdvancedSettingsDom(self):
       if not self.advancedSettingsFileProcessed:
            if(xbmcvfs.exists(self.advancedSettingsFile)):
                try:
                    file = xbmc.translatePath(self.advancedSettingsFile)
                    self.advancedSettingsFileDom = ET.parse(file)
                except Exception as e:
                    xbmc.log('% could not read advancedsettings.xml %s' % (addon_name,str(e)),xbmc.LOGDEBUG)
                    pass
            self.advancedSettingsFileProcessed = True

    def GetKodiAdvancedSettingInt(self,name,default):
        return int(self.GetKodiAdvancedSetting(name,default))

    def GetKodiAdvancedSetting(self,name,default):
        result = default
        self.LoadAdvancedSettingsDom()
        if self.advancedSettingsFileDom:
            root = self.advancedSettingsFileDom.getroot()
            child = root.find(name)
            if child is not None:
                result = child.text

        if tracing: xbmc.log("%s advancedsettings.xml %s =  %s" % (addon_name,name,result),xbmc.LOGDEBUG)
        return result



# -----------------------------------------------------------------------------------------------
    
    class PlayerState():
        playerid = None
        timerThread = None
        running = False
        updateLock = threading.RLock()
        mediaType = None
        mediaId = None
        position=None
        handleOnStop = False
        playingFile = None
        nfoFile = None
        lastQueuedMovie = None

        def reset(self):
            self.mediaType = None
            self.mediaId = None
            self.position=None
            self.playingFile = None
            self.nfoFile = None
            self.lastQueuedMovie = None

        def __init__(self, playerid):
            self.playerid = playerid

        def __str__(self):
            return 'PlayerState{playerid=%d,running=%s,handleOnStop=%s,mediaType=%s,mediaId=%s,position=%s,playingFile=%s}'% \
                (self.playerid,self.running,self.handleOnStop,self.mediaType,self.mediaId,self.position,self.playingFile)
        def __repr__(self):
            return self.__str__()

        def setMedia(self,mediaType,mediaId):
            if mediaType != self.mediaType or mediaId != self.mediaId:
                self.mediaType = mediaType
                self.mediaId = mediaId
                self.playingFile = None
                self.nfoFile = None
                if self.mediaType and self.mediaId :
                    self.playingFile = self.LookupMediaProperty("file")
                    self.nfoFile = self.findNfoFileForMedia(self.playingFile)

  
 
        def LookupMediaProperty(self,propertyName):
            if self.mediaId is None:  
                if tracing: xbmc.log('%s LookupMediaProperty(%s,None,%s)' % (addon_name,self.mediaType,propertyName), xbmc.LOGDEBUG)
                return None
            if tracing: xbmc.log('%s LookupMediaProperty(%s,%d,%s)' % (addon_name,self.mediaType,self.mediaId,propertyName), xbmc.LOGDEBUG)
            result=None
            try:
                if self.mediaType == u'movie':
                    request='{"jsonrpc":"2.0","method":"VideoLibrary.GetMovieDetails","params":{"movieid":%d,"properties":[\"%s\"]},"id":1}' %(self.mediaId,propertyName)
                    if tracing: xbmc.log("%s request: %s" % (addon_name,request),xbmc.LOGDEBUG)
                    response = xbmc.executeJSONRPC(request )
                    if tracing: xbmc.log("%s response: %s" % (addon_name,response),xbmc.LOGDEBUG)
                    result = json.loads(response)["result"]["moviedetails"][propertyName]
                elif self.mediaType == u'episode':
                    request='{"jsonrpc":"2.0","method":"VideoLibrary.GetEpisodeDetails","params":{"episodeid":%d,"properties":[\"%s\"]},"id":1}' %(self.mediaId,propertyName) 
                    if tracing: xbmc.log("%s request: %s" % (addon_name,request),xbmc.LOGDEBUG)
                    response = xbmc.executeJSONRPC(request)
                    if tracing: xbmc.log("%s response: %s" % (addon_name,response),xbmc.LOGDEBUG)
                    result = json.loads(response)["result"]["episodedetails"][propertyName]
            except Exception as e:
                xbmc.log("%s LookupMediaProperty(%s,%d,%s) failed with %s" % (addon_name, self.mediaType, self.mediaId,propertyName,e),xbmc.LOGDEBUG)

            if tracing: xbmc.log('%s LookupMediaProperty(%s,%d,%s): %s' % (addon_name,self.mediaType,self.mediaId,propertyName,result), xbmc.LOGDEBUG)       
            return result
        
        def findNfoFileForMedia(self,mediaFile):
            if tracing: xbmc.log("%s findNfoFileForMedia(%s)" % (addon_name, mediaFile),xbmc.LOGDEBUG)
            if mediaFile is None:
                return None
            filepath=None
            # handle the alternate location of movie.nfo which Kodi supports but does not recommend using
            mediaNfo = mediaFile.replace(path.splitext(mediaFile)[1], '.nfo')
            movieNfo = mediaFile.replace(path.split(mediaFile)[1], 'movie.nfo')
            if xbmcvfs.exists(mediaNfo):
                filepath = mediaNfo
            elif xbmcvfs.exists(movieNfo):
                filepath = movieNfo
            elif self.isDvdFile(mediaFile):
                fileParent = path.split(mediaFile)[0]
                (mediaHomeFolder,fileParentName) = path.split(fileParent)
                if fileParentName == "VIDEO_TS":
                    filepath= self.findSingleNfoIn(mediaHomeFolder)
            elif self.isBluerayFile(mediaFile):
                fileParent = path.split(mediaFile)[0]
                (mediaHomeFolder,fileParentName) = path.split(fileParent)
                filepath= self.findSingleNfoIn(fileParent)
                if filepath is None and fileParentName == "BDMV":
                    filepath= self.findSingleNfoIn(mediaHomeFolder)

               
            if filepath:
                if tracing: 
                    xbmc.log("{0} will be updating {1}".format(addon_name,filepath), xbmc.LOGDEBUG)
            else:
                 if tracing: 
                    xbmc.log("{0} no .nfo file corresponds to {1}".format(addon_name,mediaFile), xbmc.LOGDEBUG)
            return filepath

        def isDvdFile(self,filepath):
            filename = path.split(filepath)[1]
            result = False
            if filename.startswith("VIDEO_TS"):
                result = True
            elif filename.startswith("VTS_"):
                result = True
            if tracing: 
                xbmc.log("{0} isDvdFile({1}): {2}".format(addon_name,filepath,result), xbmc.LOGDEBUG)
            return result

        def isBluerayFile(self,filepath):
            filename = path.split(filepath)[1]
            result = False
            if filename.endswith(".bdmv"):
                result = True
            elif filename.endswith(".msts"):
                result = True
            elif filename.endswith(".mpls"):
                result = True
            if tracing: 
                xbmc.log("{0} isBluerayFile({1}): {2}".format(addon_name,filepath,result), xbmc.LOGDEBUG)
            return result

        def findSingleNfoIn(self,filepath):
            result = None
            if path.isdir(filepath):
                candidates = glob(path.join(filepath,"*.nfo"))
                if len(candidates) == 0:
                    pass
                elif len(candidates) == 1:
                    result = candidates[0]
                else:
                    pass
            if tracing: 
                xbmc.log("{0} findSingleNfoIn({1}): {2}".format(addon_name,filepath,result),xbmc.LOGDEBUG)
 
            return result


    player = [PlayerState(0),PlayerState(1)]

 
  
# -------------------------------- RPC Message handling -----------------------------------------
    def handleMsg(self, msg):
        method=None
        try:
            jsonmsg = json.loads(msg)        
            method = jsonmsg['method']
            if method in self.methodDict:
                if tracing: xbmc.log("{0} processing RPC method {1} ".format(addon_name,msg),xbmc.LOGDEBUG)
                methodHandler = self.methodDict[method]
                methodHandler(jsonmsg)
            else:
                if tracing: xbmc.log("{0} ignored RPC method {1} ".format(addon_name,msg),xbmc.LOGDEBUG)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            xbmc.log("{0} handleMsg({1}) failed with {2}".format(addon_name, msg, \
                traceback.format_exception_only(exc_type, exc_value)))
            for tracemsg in traceback.format_tb(exc_traceback):
                xbmc.log('{0} {1}'.format(addon_name,tracemsg))
            notification_msg = "handleMsg({0}) failed with {1}".format(method, \
                traceback.format_exception_only(exc_type, exc_value))
            xbmc.executebuiltin('Notification(%s, Error: %s, %d, %s)'%(addon_name,notification_msg, int(delay), addon_icon))
            xbmc.sleep(int(delay))


            

    def listen(self):
        currentBuffer = []
        msg = ''
        depth = 0
        while not xbmc.abortRequested:
            chunk = self.s.recv(1)
            currentBuffer.append(chunk)
            if chunk == '{':
                depth += 1
            elif chunk == '}':
                depth -= 1
                if not depth:
                    msg = ''.join(currentBuffer)
                    self.handleMsg(msg)
                    currentBuffer = []
        self.s.close()

# -------------------------- Message Event Handlers ----------------------------------------  
# 
# 

    def OnSeek(self,jsonmsg):
        updateOnSeek = addon.getSetting('updateonseek') == 'true'
        updateNfoOnSeek = addon.getSetting('updatenfoonseek') == 'true'
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if updateOnSeek and playerState: self.CommonSaveOnEventProcessing(playerState,jsonmsg,updateOnSeek,updateNfoOnSeek)
       
    def OnStop(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if playerState:
            if tracing: xbmc.log('%s asking worker thread to stop : %s' % (addon_name,playerState), xbmc.LOGDEBUG)       
            # tel timer thread to stop
            playerState.handleOnStop = True
            # wait for it to stop and clean it up
            self.stopTimer(playerState)
            # clear other player state variables
            if tracing: xbmc.log('%s resetting : %s' % (addon_name,playerState), xbmc.LOGDEBUG)       
            playerState.reset()
        else:
            pass

    def OnPause(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if playerState:
            self.stopTimer(playerState)
            updateOnPause = addon.getSetting('updateonpause') == 'true'
            updateNfoOnPause = addon.getSetting('updateonpause') == 'true'
            if  updateOnPause : self.CommonSaveOnEventProcessing(playerState,jsonmsg,updateOnPause,updateNfoOnPause)
       
    def OnPlay(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
      
    def OnResume(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
     
    def OnUpdate(self,jsonmsg):
        self.logEvent(jsonmsg)
        updateWatchedAtEnd = addon.getSetting('updatewatchedatend') == 'true'
        #TODO: how about the watched flag and position?
        if updateWatchedAtEnd and 'playcount' in jsonmsg['params']['data']:
            playerState = self.selectPlayerStateForMessage(jsonmsg)
            if playerState is None:
                playerState = ResumePositionUpdater.PlayerState(-1)
                playerState.setMedia(self.getItemTypeParameter(jsonmsg),self.getItemidParameter(jsonmsg))
            playcount = jsonmsg['params']['data']['playcount']
            if playcount is not None and playerState and playerState.nfoFile:
                self.CollisionTolerantPlayerNfoUpdate(playerState,self.SetNfoPlayCountCallback,playcount)

    def OnAVStart(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if playerState and (playerState.position is None or playerState.position == (0,0)):
            if tracing: xbmc.log("%s OnAVStart setting initial position for player %d " % (addon_name,playerState.playerid),xbmc.LOGDEBUG)
            playerState.position = self.GetPosition(playerState.playerid)

    def OnAdd(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlaylistOnAdd(jsonmsg)        
      

    def OnClear(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlaylistOnClear(jsonmsg)        
      

    
#----------------------------------------------------------------------------------------------------    
 
    def CommonSaveOnEventProcessing(self,playerState,jsonmsg,saveToDb,saveToNfo):
        self.logEvent(jsonmsg)
        if tracing: xbmc.log("%s CommonSaveProcessingCallback(%s,jsonmsg,saveToDb=%s,saveToNfo=%s) " % (addon_name,str(playerState),str(saveToDb),str(saveToNfo)),xbmc.LOGDEBUG)
        playerState.position = self.GetPosition(playerState.playerid)
        self.CommonSaveProcessing(playerState,saveToDb,saveToNfo)
 
    def CommonSaveProcessing(self,playerState,saveToDb,saveToNfo):
        self.IfCanLockDo(playerState.updateLock,self.CommonSaveProcessingCallback,playerState,saveToDb,saveToNfo)

    def CommonSaveProcessingCallback(self,*args):
       # (playerState,saveToDb,saveToNfo)=args
        (playerState,saveToDb,saveToNfo)= args
        if tracing: xbmc.log("%s CommonSaveProcessingCallback(%s,saveToDb=%s,saveToNfo=%s) " % (addon_name,str(playerState),str(saveToDb),str(saveToNfo)),xbmc.LOGDEBUG)
        if self.PositionInRange(playerState.position):
            if saveToDb:self.SavePositionToDb(playerState)
            if saveToNfo:self.CollisionTolerantPlayerNfoUpdate(playerState,self.SavePositionToNfoCallback)
        else:
            #TODO: how to remove the position from the DB here?
            if saveToNfo and self.PlayerAtEnd(playerState.position):
                self.CollisionTolerantPlayerNfoUpdate(playerState,self.EndOfMediaNfoUpdateCallback )
 
# -----------------------------------------------------------------------------------------------------
    # determine which playerState is associated with the media referenced in the JSON message
    # may return None
    def selectPlayerStateForMessage(self,jsonmsg):
        selectedPlayer=None
        itemType = self.getItemTypeParameter(jsonmsg)
        playerId = self.getPlayeridParameter(jsonmsg)
        itemId = self.getItemidParameter(jsonmsg)
        if playerId is not None:
            selectedPlayer = self.player[playerId]
        elif  itemType is not None and itemId is not None:
            for p in self.player:
                if p.mediaId == itemId and p.mediaType == itemType:
                    selectedPlayer=p
                    break
            if  selectedPlayer is None:
                xbmc.log('%s no player seems to be playing %s %d' %  \
                     (addon_name,itemType, itemId),  \
                      xbmc.LOGDEBUG)
        if selectedPlayer is not None and itemType is not None:
            if itemId is not None:
                selectedPlayer.setMedia(itemType,itemId)
            else:
                title = self.getTitleParameter(jsonmsg)
                if tracing:
                    xbmc.log('%s checking for Blueray title=%s lastQueuedMovie=%s' %\
                        (addon_name, title,str(selectedPlayer.lastQueuedMovie)),xbmc.LOGDEBUG)
                if itemType == "movie" and title.startswith("Play main title:") and selectedPlayer.lastQueuedMovie is not None:
                    xbmc.log('%s appears to be starting from the Bluray index.bdmv' %\
                        (addon_name),xbmc.LOGDEBUG)
                    selectedPlayer.setMedia(itemType,selectedPlayer.lastQueuedMovie)
        return selectedPlayer
         
    def getPlayeridParameter(self,jsonmsg):
        try:
            playerid = int(jsonmsg["params"]["data"]["player"]["playerid"])
            return playerid
        except Exception as e:
            pass
            if tracing: xbmc.log('%s bad or missing JSON params data player playerid %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
         
    def getItemidParameter(self,jsonmsg):
        try:
            playerid = int(jsonmsg["params"]["data"]["item"]["id"])
            return playerid
        except Exception as e:
            pass
            if tracing: xbmc.log('%s bad or missing JSON params data item id %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
        
    def getPlaycountParameter(self,jsonmsg):
        try:
            playcount = int(jsonmsg["params"]["data"]["playcount"])
            return int(playcount)
        except Exception as e:
            pass
            if tracing: xbmc.log('%s bad or missing JSON params data item id %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
         
    def getTitleParameter(self,jsonmsg):
        try:
            playerid = jsonmsg["params"]["data"]["item"]["title"]
            return playerid
        except Exception as e:
            pass
            if tracing: xbmc.log('%s bad or missing JSON params data item id %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
         
    def getItemTypeParameter(self,jsonmsg):
        try:
            itemType = jsonmsg["params"]["data"]["item"]["type"]
            return itemType
        except Exception as e:
            pass
            if tracing: xbmc.log('%s bad or missing JSON params data item type %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
 
 

    def handlePlayerStarting(self,jsonmsg):
        playerState=self.selectPlayerStateForMessage(jsonmsg)
     
        tasks = list()
        now = time()
        if addon.getSetting('updateperiodically') == 'true':
            period  = int(addon.getSetting('updateperiod'))       
            task=self.TimerTask("Update Db for player"+str(playerState.playerid), \
                playerState,period,self.SaveToDbPeriodicallyTask,now)
            tasks.append(task)
        if playerState.nfoFile and addon.getSetting('updatenfoonstop') == "true":
            onStopAccuracy = int(addon.getSetting('endofmediaaccuracy'))
            task=self.TimerTask("Remember Position for OnStop player"+str(playerState.playerid),  \
                playerState,onStopAccuracy,self.SavePositionForOnStopTask,now)
            tasks.append(task)

        if tasks: 
            self.startTimer(playerState,tasks)
        else:
            self.stopTimer(playerState)

    def SavePositionForOnStopTask(self,playerState): 
        if tracing: xbmc.log('%s SavePositionForOnStopTask(%s)' % (addon_name, playerState),xbmc.LOGDEBUG)
        #TODO what happens here
        pass

    def SaveToDbPeriodicallyTask(self,playerState):
        if self.PositionInRange(playerState.position):
            if tracing: xbmc.log('%s thread %s on period invoking SavePositionToDb(%s,%s,%s) ' \
                    % (addon_name,threading.currentThread().name,str(playerState.position), \
                        playerState.mediaType,playerState.mediaId), \
                xbmc.LOGDEBUG)
            self.CommonSaveProcessing(playerState,True,False)
            
    # returns True if the position of the player is between the start and end regions.
    # this is used to prevent resume poistions being saved at the fornt and end of the media
    # especially common cases where the play is stopped when the end credits roll
    def PositionInRange(self,position):
        result=False
        if tracing: xbmc.log('%s PositionInRange(%s) ignoresecondsatstart=%s ignorepercentatend=%s' \
            % (addon_name,str(position),str(self.ignoresecondsatstart),str(self.ignorepercentatend)),xbmc.LOGDEBUG)
        if  position:
            if position[1] == 0:
                # some DVD video segment have a 0 total time
                result = False
                if tracing: xbmc.log('%s perentComplete video segment position (%d,%d) has no known length' % (addon_name,position[0],position[1])) 
            else:
                startPercentage = 100.0*self.ignoresecondsatstart / position[1]
                endPercentage = 100.0 - self.ignorepercentatend
                percentComplete = 100.0 * position[0] / position[1]
                result = percentComplete >= startPercentage and percentComplete <= endPercentage
                if tracing: xbmc.log('%s perentComplete %f is %sin range (%f,%f)' % (addon_name,percentComplete,  \
                    '' if result else 'not ',startPercentage,endPercentage),xbmc.LOGDEBUG)
        return result

        
    # returns True of the player position meets the criteria for the "end" of the media.
    # this varies depending on where the advanced settings are being honored.
    def PlayerAtEnd(self,position):
        if not position: return False
        if position[0] >= position[1]:
            return True
        if addon.getSetting('honoradvsettings') == 'true':
            percentComplete = 100.0 * position[0] / position[1]
            return percentComplete > 100.0-self.ignorepercentatend
        else:
            timeRemaining = position[1] - position[0]
            return timeRemaining <=  int(addon.getSetting('endofmediaaccuracy'))



    def handlePlaylistOnAdd(self, jsonmsg):
        # keep track of the movie id when it is queued. In some edge cases the OnPlay message will
        # no have a movie id 
        try:
            playlistId = int( jsonmsg["params"]["data"]["playlistid"] )
            position = int( jsonmsg["params"]["data"]["position"] ) 
            itemType = jsonmsg["params"]["data"]["item"]["type"]       
            itemId = int(jsonmsg["params"]["data"]["item"]["id"] ) 
            if playlistId == 1 and position == 0 and itemType == "movie" and itemId is not None:
               if tracing: xbmc.log("%s OnAdd saving queued movie id %d" %(addon_name,itemId),xbmc.LOGDEBUG)
               self.player[playlistId].lastQueuedMovie = itemId
            else:
                self.player[playlistId].lastQueuedMovie = None
        except:
            pass


    def handlePlaylistOnClear(self, jsonmsg):
        try:
            playlistId = int( jsonmsg["params"]["data"]["playlistid"] )
            if playlistId == 1 :
                self.player[playlistId].lastQueuedMovie = None
        except:
            pass

 

 
# -------------- periodic update code --------------------------

    class TimerTask():
        def __init__(self,name, playerState,period, callback,now):
            self.name = name
            self.period = period
            self.nextTime = now+period
            self.callback = callback
            self.playerState = playerState
            self.threadName = threading.currentThread().name

        def computeNextTime(self,now):
            self.nextTime += self.period
            if self.nextTime < now:
                if self.nextTime+self.period > now: # close, so skip to the next
                    self.nextTime+=self.period
                else:
                    self.nextTime = now+self.period # way off, rebaseline our ticks

        def __str__(self):
            return "TimerTask{name=%s,period=%d,nextTime=%f,state=%s}"  % \
                 (self.name, self.period, self.nextTime,self.playerState)

        def __repr__(self):
            return self.__str__()

    def NextTick(self,tasks,lastTick):
        if tracing: xbmc.log("%s NextTick(%s,%s)" %(addon_name,tasks,lastTick),xbmc.LOGDEBUG)
        now = time()
        nextTime = now+24*60*60
        for task in tasks: nextTime = min(nextTime, task.nextTime)
        if tracing: xbmc.log("%s %f=NextTick(%s,%s)" %(addon_name,nextTime,tasks,lastTick),xbmc.LOGDEBUG)
        return nextTime

    # runs on the timerThread to update the position periodically while the player is playing
    # Sleeps in increments of 100ms so the thread can  be quickly an cleanly terminated by setting running false
    # period is based on real time, not on media position. 
    def PeriodicUpdate(self,playerState,tasks):
        threadName = threading.current_thread().name
        playerState.running = True
        abortRequested = False

        now = time()
        maxSleep=0.1

        try:
            while playerState.running:
                # micronap til next tick while ready for aborts or stop requests
                nextTick = self.NextTick(tasks,time())
                now = time()
                while playerState.running and now < nextTick:
                    timeTilNextTick = nextTick-now
                    timeToSleep = max(0.01,min(maxSleep, timeTilNextTick))
                    sleep(timeToSleep)
                    now = time()  
                    abortRequested = self.monitor.abortRequested()
                    if abortRequested : 
                        playerState.running = False
                        if tracing: xbmc.log('%s thread %s abort request received' % \
                            (addon_name,threadName), \
                                xbmc.LOGDEBUG)
                # we're at t nextTick, execute any tasks that are ready to go
                if not abortRequested and playerState.running:
                    playerState.position = self.GetPosition(playerState.playerid)
                    for task in tasks:
                        if tracing: xbmc.log("%s" % (task),xbmc.LOGDEBUG)
                        if task.nextTime <= now :
                            if tracing: xbmc.log('%s  thread %s executing %s '  \
                                 % (addon_name,playerState.timerThread.name,task.name),  \
                                   xbmc.LOGDEBUG)
                            task.callback(playerState)
                            task.computeNextTime(now)
                            if tracing: xbmc.log("%s task.nextTime=%f" %(addon_name,task.nextTime),xbmc.LOGDEBUG)
            # thread is stopping
            updateNfoOnStop = addon.getSetting('updatenfoonstop') == "true"
            if not abortRequested and updateNfoOnStop and playerState.handleOnStop:
                if tracing: xbmc.log('%s thread %s saving to NFO on stop' % \
                            (addon_name,threadName), \
                                xbmc.LOGDEBUG)
                                    
                if addon.getSetting('removeonendofmedia') == 'true' and self.PlayerAtEnd(playerState.position):
                    self.CollisionTolerantPlayerNfoUpdate(playerState,self.EndOfMediaNfoUpdateCallback )
                else:
                    self.CollisionTolerantPlayerNfoUpdate(playerState,self.SavePositionToNfoCallback)
            if tracing: xbmc.log('%s thread %s exiting normally' % (addon_name,threadName),\
                xbmc.LOGDEBUG)
        except Exception:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            xbmc.log("{0} thread {1} failed with {2}".format(addon_name, threading.currentThread().getName(),\
                traceback.format_exception_only(exc_type, exc_value)))
            for tracemsg in traceback.format_tb(exc_traceback):
                xbmc.log('{0} {1}'.format(addon_name,tracemsg))
            notification_msg = "{0} thread {1} failed with {2}".format( addon_name, threading.currentThread().getName(),\
                traceback.format_exception_only(exc_type, exc_value))
            xbmc.executebuiltin('Notification(%s, Error: %s, %d, %s)'%(addon_name,notification_msg, int(delay), addon_icon))
            xbmc.sleep(int(delay))
        finally:
            playerState.running = False
            playerState.handleOnStop = False
            playerState.position = None
            playerState.timerThread = None
            
    # starts a new periodic timer on the player, destroying the current one if it exists
    def startTimer(self,playerState,tasks): 
        if playerState.timerThread :
            self.stopTimer(playerState)
        playerState.timerThread = threading.Thread(target=self.PeriodicUpdate,args=(playerState,tasks))
        playerState.timerThread.setName(addon_name+" periodic update for player "+str(playerState.playerid))
        if tracing: xbmc.log('%s starting thread %s  '  \
               % (addon_name,playerState.timerThread.name),  \
                   xbmc.LOGDEBUG)
        playerState.timerThread.start()
 
    # stops and destroys the current time thread if it exists
    def stopTimer(self,playerState):
        if  not playerState.playerid == None  and playerState.timerThread :
            if tracing: xbmc.log('%s stopping thread %s '  \
               % (addon_name,playerState.timerThread.name),  \
                   xbmc.LOGDEBUG)
            playerState.running = False
            playerState.timerThread.join()
            playerState.timerThread = None

    def stopAllTimers(self):
        for playerState in self.player:
            self.stopTimer(playerState)

# ---------------------------------------------------------------------------------
           
    def logEvent(self,  jsonmsg):
         if tracing: xbmc.log('%s method: %s message: %s' \
             % (addon_name,jsonmsg["method"],str(jsonmsg)),\
             xbmc.LOGDEBUG)

       
 
        
    # save the position to the database (unless another thread is already doing so )
    # if another thread is already updating it we can safely return because the other thread
    # has the same data a this one.
    def SavePositionToDb(self, playerState):
        if playerState.mediaId:
             self.IfCanLockDo(playerState.updateLock,self.SavePositionToDbCallback, 
             playerState.mediaType,playerState.mediaId,playerState.position)
 
    # does the work of saving the resume position to the media DB 
    # requires args  mediaType, mediaId, and a position tuple
    def SavePositionToDbCallback(self,*extras):
        (mediaType,mediaId,position) = extras
        if tracing: xbmc.log("%s SavePositionToDbCallback(%s,%d,(%d,%d)) " % (addon_name,mediaType,mediaId,position[0],position[1]),xbmc.LOGDEBUG)
        if mediaType == 'movie':
            self.SaveMoviePositionToDb(mediaId, position)
        elif mediaType == 'episode':
            self.SaveEpisodePositionToDb( mediaId, position)
        elif mediaType == 'song':
            pass
        else:
            if tracing: xbmc.log("%s media type %s not known by SavePositionToDbCallback)" % (addon_name,mediaType),xbmc.LOGDEBUG)
            pass
  
    # get the position from the player. Returns a tuple (int time, int totaltime) or None
    def GetPosition(self, playerid):

        position = None
        try:
            query = '{"jsonrpc":"2.0","method":"Player.GetProperties","params":{"playerid":%d,"properties":["time","totaltime"]},"id":1}'  % \
                (playerid)
            if tracing: xbmc.log('%s position query for player %d is %s ' %  \
                (addon_name,playerid,query), \
                xbmc.LOGDEBUG)
            msg = xbmc.executeJSONRPC( query )
            if tracing: xbmc.log('%s result of position query for player %d is %s' % \
                 (addon_name,playerid,msg), \
                     xbmc.LOGDEBUG)
            jsonmsg = json.loads(msg)
            time = self.convertTimeToSeconds(jsonmsg["result"]["time"])
            totalTime = self.convertTimeToSeconds(jsonmsg["result"]["totaltime"])
            position = (time, totalTime)
            if tracing: xbmc.log("%s final position is %s" % (addon_name,str(position)),xbmc.LOGDEBUG)
        except Exception as e:
            if tracing: xbmc.log("{0} failed to determine player position {1} ".format(addon_name,str(e)),xbmc.LOGDEBUG)
        return position
 
    def ExecuteSavePositionCommand(self,command):
        if tracing: xbmc.log("%s save position command %s" % (addon_name,command), \
            xbmc.LOGDEBUG)
        msg = xbmc.executeJSONRPC( command )
        if tracing: xbmc.log("%s save position response %s" % (addon_name,msg), \
            xbmc.LOGDEBUG)
        jsonmsg = json.loads(msg)
        return  "result" in jsonmsg and jsonmsg["result"] == "Ok" 


    def SaveMoviePositionToDb(self, mediaId, resumePoint):
            command = '{"jsonrpc":"2.0", "id": 1, "method":"VideoLibrary.SetMovieDetails","params":{"movieid":%d,"resume":{"position":%d,"total":%d}}}' %\
                 (mediaId,resumePoint[0], resumePoint[1])
            return self.ExecuteSavePositionCommand(command)
  
    def SaveEpisodePositionToDb(self, mediaId, resumePoint):
            command = '{"jsonrpc":"2.0", "id":1, "method":"VideoLibrary.SetEpisodeDetails","params":{"episodeid":%d,"resume":{"position":%d,"total":%d}}}' % \
                (mediaId,resumePoint[0], resumePoint[1])
            return self.ExecuteSavePositionCommand(command)
       
    def convertTimeToSeconds(self, jsonTimeElement):
        hours =  int( jsonTimeElement["hours"])
        minutes = int( jsonTimeElement["minutes"])
        seconds = int( jsonTimeElement["seconds"])
        return 3600*hours + 60*minutes + seconds
# -----------------------------------------------------------------------------------------------

    class FileWriteCollision(Exception):
        def __init__(self,message):
            self.message = message
        pass

    # upodates the nfo file associated with the player using the callback to perform edits on the DOM
    # This deals with possible nfo update collisikon between multiple threads by detecting collisions. 
    # if a collisikon occurs it tries again.
    def CollisionTolerantPlayerNfoUpdate(self,playerState,callback,*extras):
        if tracing: xbmc.log('%s CollisionTolerantPlayerNfoUpdate(%s,%s,%s)' %(addon_name,playerState,callback,extras),xbmc.LOGDEBUG)
        if playerState.playingFile is None:
           if tracing: xbmc.log("%s no known file is playing so can't find corresponding nfo" % (addon_name), xbmc.LOGDEBUG)
           return
        nfoFile = playerState.nfoFile
        if nfoFile and xbmcvfs.exists(nfoFile):
            attempts=0
            done = False
            success = False
            changes = False
            while not done and attempts <= 3:
                try:
                    attempts += 1
                    (dom,readstat) = self.ReadXmlFileIntoDom(playerState.nfoFile)
                    result = callback(playerState,dom,*extras)
                    if tracing: xbmc.log("%s callback result is %s" %(addon_name, str(result)), xbmc.LOGDEBUG)
                    (success,dirty) = result
                    if success:
                        done=True
                        if dirty:
                            changes = True
                            success = self.WriteDomToXmlFile(dom,playerState.nfoFile,readstat)
                    else:
                        if tracing: xbmc.log("%s update of %s failed" % (addon_name, playerState.nfoFile), xbmc.LOGDEBUG)
                except self.FileWriteCollision as e:
                    # something else touched the file between the time we read it and now. Wait a bit and try again
                    if tracing: xbmc.log('%s FileWriteCollision %s on %s' %(addon_name,e.message,playerState.nfoFile),xbmc.LOGDEBUG)
                    sleep(0.001+random.random()*0.001)
                    pass
            if  success:
                if changes:
                    if tracing: xbmc.log('%s updated %s' % (addon_name,playerState.nfoFile),xbmc.LOGDEBUG)
                else:
                    if tracing: xbmc.log("%s no changes to %s needed" %(addon_name, playerState.nfoFile), xbmc.LOGDEBUG)
            else:
                if tracing: xbmc.log('%s failed to update %s' % (addon_name,playerState.nfoFile),xbmc.LOGDEBUG)
        else:
            if tracing: xbmc.log("%s no nfo file to update for %s" % (addon_name, playerState.playingFile), xbmc.LOGDEBUG)

  
    # remove the resume element from the nfo when the player is at or near the edge or the media
    def EndOfMediaNfoUpdateCallback(self,playerState,dom,*extras):
        success=True
        dirty=False
        if tracing: xbmc.log('%s EndOfMediaNfoUpdateCallback(%s,%s,%s)' %(addon_name,playerState,dom,extras),xbmc.LOGDEBUG)
        dirty = self.RemoveElement(dom.getroot(),"resume")
        return (success,dirty)
 
    # maintains the nfo watched, playcount, and lastplayed elements
    def SetNfoPlayCountCallback(self,playerstate,dom,*extras):
        playcount=extras[0]
        if tracing: xbmc.log('%s SetNfoPlayCountCallback(%s,dom,%s)' %(addon_name,str(playerstate),str(playcount)),xbmc.LOGDEBUG)
        root=dom.getroot()
        dirty=False
        if playcount > 0:
            dirty = self.SetSimpleElement(root,'playcount',playcount) or dirty
            dirty = self.SetSimpleElement(root,'watched','true') or dirty
            dirty = self.SetSimpleElement(root,'lastplayed',datetime.today().date()) or dirty
        else:
            dirty = self.RemoveElement(root,'playcount') or dirty
            dirty = self.SetSimpleElement(root,'watched','false') or dirty
            dirty = self.SetSimpleElement(root,'lastplayed','') or dirty
        return (True,dirty)
 

    # maintains the resume element in the dom
    def SavePositionToNfoCallback(self, playerState,dom,*extras):
        if tracing: xbmc.log("%s thread %s SavePositionToNfoCallback(%s)" % (addon_name,threading.current_thread().name,playerState),xbmc.LOGDEBUG)
        success=False
        dirty=False
        if playerState.position:
            root = dom.getroot()
            (resumeElement,dirty) = self.findOrCreateElement(root,'resume', True)
            dirty = self.SetSimpleElement(resumeElement,'position',playerState.position[0]) or dirty
            dirty = self.SetSimpleElement(resumeElement,'total',playerState.position[1]) or dirty
            success=True
        else:
            if tracing: xbmc.log("%s thread %s SavePositionToNfoCallback failed: no known position" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
        return (success,dirty)
 
 # ------------- XML file and DOMUtility methods ------------------------------------------------------

    def SetSimpleElement(self,parentElement,elementName,value):
        if tracing: xbmc.log("%s thread SetSimpleElement(%s,%s,%s)" % (addon_name,parentElement,elementName,str(value)),xbmc.LOGDEBUG)
        dirty=False
        element = parentElement.find(elementName)
        if element == None:
            element = ET.SubElement(parentElement,elementName)
            dirty=True
        currentValue = element.text
        if ( str(value) != currentValue ): 
            element.text = str(value)
            dirty = True
        return dirty


    def RemoveElement(self,parentElement,elementName):
        dirty = False
        element = parentElement.find(elementName)
        if element is not None:
            parentElement.remove(element)
            dirty = True
        return dirty


    # reads the XML file path into a ElementTree DOM
    def ReadXmlFileIntoDom(self, filepath):
        dom=None
        filestat=None
 
        if filepath is not None and xbmcvfs.exists(filepath):
            filestat=xbmcvfs.Stat(filepath)
            xml = self.readFile(filepath)
            dom = None
            if not xml:
                xbmc.log("{0} NFO is not readable  {1}".format(addon_name,filepath), xbmc.LOGDEBUG)
            else: 
                dom=self.parseXml(xml)
                if dom is None:
                    xbmc.log("{0} NFO is not XML  {1}".format(addon_name,filepath), xbmc.LOGDEBUG)
        return (dom,filestat)

    # writes the element tree DOM into the filepath and checks the result. If the write was not
    # successful due to another thread updating the same file a FileWriteCollision is raised.
    def WriteDomToXmlFile(self,dom,filepath,oldfilestat):
        root = dom.getroot()
        self.prettyPrintXML(root)
        xml = ET.tostring(root, encoding='UTF-8')
        if not xml:
            xbmc.log("{0}  XML creation failed".format(addon_name), xbmc.LOGDEBUG)
            return False
        #if tracing: xbmc.log("{0} created xml is {1}".format(addon_name, str(xml)), xbmc.LOGDEBUG)

        if oldfilestat:
            currentfilestat=xbmcvfs.Stat(filepath)
 #           if tracing: xbmc.log("%s %s size  read %d  now %d" % (addon_name, filepath,currentfilestat.st_size(),oldfilestat.st_size() ),xbmc.LOGDEBUG)
            if currentfilestat.st_size() != oldfilestat.st_size():
                raise self.FileWriteCollision("size changed since read")
 #           if tracing: xbmc.log("%s %s modified time read  %d now %d" % (addon_name, filepath,currentfilestat.st_mtime(), oldfilestat.st_mtime() ),xbmc.LOGDEBUG)
            if currentfilestat.st_mtime() != oldfilestat.st_mtime():
                raise self.FileWriteCollision("modified time changed since read")

        result=self.writeFile(filepath, xml)
        readStat=xbmcvfs.Stat(filepath)
 #       if tracing: xbmc.log("%s %s file size %d vs, the XML %d" % (addon_name,filepath,readStat.st_size(),len(xml)),xbmc.LOGDEBUG)
        if readStat.st_size() != len(xml):
            raise self.FileWriteCollision("after-write file size not same as the XML") 

        if result: xbmc.log("{0} succesfully updated {1}".format(addon_name, filepath), xbmc.LOGDEBUG)
        return result


    # utility to ensure a named element exists as a child of the parenet element n the ElementTree dom
    def findOrCreateElement( self,  parent, elementName, okToCreate):
        xbmc.log("{0} findOrCreateElement  {1}, {2}, {3} ".format(addon_name,str(parent),str(elementName),str(okToCreate)), xbmc.LOGDEBUG)
        dirty=False
        result = parent.find(elementName)
        if result == None and okToCreate:
            result = ET.SubElement(parent,elementName)
            dirty=True
        return (result,dirty)

    # write a file to disk
    def writeFile(self, filepath, contents):
        dFile = None
        result = False
        try:
            dFile = xbmcvfs.File(filepath, 'w')
            dFile.write(contents) 
            result = True
        except Exception as e:
            xbmc.log("{0} I/O Error writing {1}, {2}".format(addon_name, filepath, str(e)),xbmc.LOGDEBUG)
        finally:
            if dFile is not None: dFile.close()
        return result
            


    # adds whitespace to the dom to create a human-readable representation of the ElementTree DOM rooted at the
    # given element
    def prettyPrintXML(self, elem, level=0):
        i = '\n' + level * '  '
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
            for elem in elem:
                self.prettyPrintXML(elem, level+1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    # reads the contents of the file into a string           
    def readFile(self,filepath):
        sFile = None
        try:
            sFile = xbmcvfs.File(filepath)
            currentBuffer = []
            msg = ''
            while True:
                buf = sFile.read(1024)
                currentBuffer.append(buf)
                if not buf:
                    msg = ''.join(currentBuffer)                    
                    break
        except Exception:
            pass
        finally:
            if sFile is not None: sFile.close()
        return msg

    # Parses the string representation of an XML document into an ElementTree DOM
    def parseXml(self,xml):
            try:
                tree = ET.ElementTree(ET.fromstring(xml))
                return tree
            except Exception as err:
                xbmc.log("{0} bad xml: {1}".format(addon_name,str(err)), xbmc.LOGDEBUG)
            return None

    # sets the DOM elements text to the string value and returns True if the value actually changed       
    def setElementText(self, element, value):
        if tracing: xbmc.log("{0} setElementText  {1}, {2}, ".format(addon_name,str(element),str(value)), xbmc.LOGDEBUG)
        currentValue = element.text
        if ( str(value) == currentValue ): return False
        element.text = str(value)
        return True

      
# ----------------------------------------------------------------------------------------

# acquires the lock and executes the callback method. Lock is always release on return
    def WithLockDo(self,lock,method,*args):
        result = None
        lock.acquire()    
        if tracing: xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
        try:
            result = method(*args)
        finally:
            lock.release()
        return result


# Attempt to acquire the lock and executes the callback method. 
# Resturns the result of the callback or None if the locak cannot be acquired
    def IfCanLockDo(self,lock,method,*args):
        result = None
        if lock.acquire(blocking=False):    
            if tracing: xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
            try:
                result  = method(*args)
            finally:
                lock.release()
        else:
            if tracing: xbmc.log("%s thread %s dit not acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)

        return result


# ----------------------------------------------------------------------------------------
if __name__ == '__main__':
    WU = ResumePositionUpdater()
    WU.listen()
    del WU
