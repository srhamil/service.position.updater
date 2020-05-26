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
import socket
import json
import xml.etree.ElementTree as ET
import threading
from time import sleep
from time import time



addon = xbmcaddon.Addon('service.position.updater')
addon_name = addon.getAddonInfo('name')

delay = '4000'
logo = 'special://home/addons/service.position.updater/icon.png'





class ResumePositionUpdater():
    class PlayerState():
        playerid = None
        timerThread = None
        running = False
        updateLock = threading.RLock()
        mediaType = None
        mediaId = None
        def __init__(self, playerid):
            self.playerid = playerid

        def __str__(self):
            return 'PlayerState{playerid=%d,running=%s,mediaType=%s,mediaId=%d}'% \
                (self.playerid,self.running,self.mediaType,self.mediaId)
        def __repr__(self):
            return self.__str__()

    player = [PlayerState(0),PlayerState(1)]
 
 

    monitor = xbmc.Monitor()

    def __init__(self):
        self.methodDict = {"Player.OnPause": self.OnPause,
                          "Player.OnPlay": self.OnPlay,
                          "Player.OnResume": self.OnResume,
                          "Player.OnSeek": self.OnSeek,
                          "Player.OnStop": self.OnStop,
                          }

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
                
# -------------------------------- RPC Message handling -----------------------------------------
    def handleMsg(self, msg):
        jsonmsg = json.loads(msg)        
        method = jsonmsg['method']
        #xbmc.log("{0} handlemsg {1} ".format(addon_name,msg),xbmc.LOGDEBUG)
        if method in self.methodDict:
            methodHandler = self.methodDict[method]
            methodHandler(jsonmsg)
            

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
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if ( updateOnSeek ) : self.CommonSaveOnEventProcessing(playerState,jsonmsg)
       
    def OnStop(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        self.stopTimer(playerState)

    def OnPause(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        self.stopTimer(playerState)
        updateOnPause = addon.getSetting('updateonpause') == 'true'
        if  updateOnPause : self.CommonSaveOnEventProcessing(playerState,jsonmsg)
       
    def OnPlay(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
      
    def OnResume(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
 
    def CommonSaveOnEventProcessing(self,playerState,jsonmsg):
        if  playerState.updateLock.acquire(blocking=False):
            xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
            try:
                self.logEvent(jsonmsg)
                position = self.GetPosition(playerState.playerid)
                if position:self.SavePosition(playerState.mediaType, playerState.mediaId, position,playerState.playerid)
            finally:
                playerState.updateLock.release()
                xbmc.log("%s thread %s released lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
        else:
            pass
            xbmc.log("%s thread %s failed to acquire lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)

    def selectPlayerStateForMessage(self,jsonmsg):
        if jsonmsg["method"] == "Player.OnStop":
            itemid = jsonmsg["params"]["data"]["item"]["id"]
            itemtype = jsonmsg["params"]["data"]["item"]["type"]
            for playerState in self.player:
                if playerState.mediaId == itemid and playerState.mediaType == itemtype:
                    return  playerState
            xbmc.log('%s no player seems to be playing %s %d' %  \
                (addon_name,itemtype, itemid),  \
                xbmc.LOGDEBUG)
            return None
        else:
            return self.player[self.getPlayeridParameter(jsonmsg)]


    def handlePlayerStarting(self,jsonmsg):
        (mediaId,mediaType,playerId) = self.getParameters(jsonmsg)
        playerState = self.player[playerId]
        playerState.mediaId = mediaId
        playerState.mediaType = mediaType
        updatePeriodically = addon.getSetting('updateperiodically') == 'true'
        if ( updatePeriodically ): 
            period  = int(addon.getSetting('updateperiod'))       
            self.startTimer(playerState,period)
        else:
            self.stopTimer(playerState)
 
# -------------- periodic update code --------------------------

    # runs on the timerThread to update the position periodically while the player is playing
    # Sleeps in increments of 100ms so the thread can  be quickly an cleanly terminated by setting running false
    # period is based on real time, not on media position. 
    def PeriodicUpdate(self,period,playerState):
        threadName = threading.current_thread().name
        maxSleep=0.1
        period = max(1,period)
        timeRemaining = period
        nextTick = time()+timeRemaining
        playerState.running = True
        try:
            while playerState.running:
                while playerState.running and timeRemaining > 0:
                    timeToSleep = min(maxSleep, timeRemaining)
                    sleep(timeToSleep)
                    timeRemaining = max(0, nextTick-time() )
                    if ( self.monitor.abortRequested() ): playerState.running = False
                if ( playerState.running ):
                    position = self.GetPosition(playerState.playerid)
                    xbmc.log('%s thread %s invoking SavePosition(%s,%s,%d)' \
                            % (addon_name,threadName,str(position),playerState.mediaType,playerState.mediaId),\
                                xbmc.LOGDEBUG)
                    self.SavePosition(playerState.mediaType,playerState.mediaId,position,playerState.playerid)  
                    nextTick = nextTick+period
                    timeRemaining = period

            xbmc.log('%s thread %s exiting normally' % (addon_name,threadName) \
                ,xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("%s thread died due %s to %s" % \
                  (addon_name,threadName,str(e)),  \
                      xbmc.LOGDEBUG)
        playerState.running = False
        playerState.timerThread = None
            
    # starts a new periodic timer on the player, destroying the current one if it exists
    def startTimer(self,playerState,period): 
        if playerState.timerThread :
            self.stopTimer(playerState)
        playerState.timerThread = threading.Thread(target=self.PeriodicUpdate,args=(period,playerState))
        playerState.timerThread.setName(addon_name+" periodic update for player "+str(playerState.playerid))
        xbmc.log('%s starting thread %s period=%d '  \
               % (addon_name,playerState.timerThread.name,period),  \
                   xbmc.LOGDEBUG)
        playerState.timerThread.start()
 
    # stops and destroys the current time thread if it exists
    def stopTimer(self,playerState):
        if  not playerState.playerid == None  and playerState.timerThread :
            xbmc.log('%s stopping thread %s '  \
               % (addon_name,playerState.timerThread.name),  \
                   xbmc.LOGDEBUG)
            playerState.running = False
            playerState.timerThread.join()
            playerState.timerThread = None

    def stopAllTimers(self):
        for playerState in self.player:
            self.stopTimer(playerState)

# ---------------------------------------------------------------------------------
    def getParameters(self,jsonmsg):
        try:
            itemid = jsonmsg["params"]["data"]["item"]["id"]
            itemtype = jsonmsg["params"]["data"]["item"]["type"]
            playerid = int(jsonmsg["params"]["data"]["player"]["playerid"])
            xbmc.log('%s params itemid: %d itemtype: %s playerid: %d' %\
                (addon_name, itemid, itemtype,playerid), \
                xbmc.LOGDEBUG)
            return ( itemid, itemtype, playerid )
        except Exception as e:
            pass
            xbmc.log('%s ignoring event, bad or missing params %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return (None,None,None)
           
    def getPlayeridParameter(self,jsonmsg):
        try:
            playerid = int(jsonmsg["params"]["data"]["player"]["playerid"])
            return playerid
        except Exception as e:
            pass
            xbmc.log('%s ignoring event, bad or missing params %s %s' %\
                        (addon_name, jsonmsg, e),xbmc.LOGDEBUG)
        return None
           
    def logEvent(self,  jsonmsg):
         xbmc.log('%s method: %s message: %s' \
             % (addon_name,jsonmsg["method"],str(jsonmsg)),\
             xbmc.LOGDEBUG)

    # save the position to the database (unless another thread is already doing so 
    def SavePosition(self, mediaType, mediaId, position,playerId):
        if self.player[playerId].updateLock.acquire(blocking=False):
            xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
            try :
                if mediaType == 'movie':
                    self.SaveMoviePosition(mediaId, position)
                elif mediaType == 'episode':
                    self.SaveEpisodePosition( mediaId, position)
                #TODO: if Kodi ever supports resume position in the database for audio (e.g. audiobook or podcast) handle it here.
                #elif mediaType == 'song':
                #    self.SaveSongPosition( mediaId, position)
                else:
                    pass
                    xbmc.log("%s media type %s not supported by SavePosition)" % (addon_name,mediaType),xbmc.LOGDEBUG)
            finally:
                self.player[playerId].updateLock.release()
                xbmc.log("%s thread %s released lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
        else:
            pass
            xbmc.log("%s thread %s failed to acquire lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)

    # get the position from the player. Returns a tuple (int time, int totaltime) or None
    def GetPosition(self, playerid):
        position = None
        try:
            query = '{"jsonrpc":"2.0","method":"Player.GetProperties","params":{"playerid":%d,"properties":["time","totaltime"]},"id":1}'  % \
                (playerid)
            xbmc.log('%s position query for player %d is %s ' %  \
                (addon_name,playerid,query), \
                xbmc.LOGDEBUG)
            msg = xbmc.executeJSONRPC( query )
            xbmc.log('%s result of position query for player %d is %s' % \
                 (addon_name,playerid,msg), \
                     xbmc.LOGDEBUG)
            jsonmsg = json.loads(msg)
            time = self.convertTimeToSeconds(jsonmsg["result"]["time"])
            totalTime = self.convertTimeToSeconds(jsonmsg["result"]["totaltime"])
            position = (time, totalTime)
            xbmc.log("%s final position is %s" % (addon_name,str(position)),xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("{0} failed to determine player position {1} ".format(addon_name,str(e)),xbmc.LOGINFO)
        return position
 
    def ExecuteSavePositionCommand(self,command):
        xbmc.log("%s save position command %s" % (addon_name,command), \
            xbmc.LOGDEBUG)
        msg = xbmc.executeJSONRPC( command )
        xbmc.log("%s save position response %s" % (addon_name,msg), \
            xbmc.LOGDEBUG)
        jsonmsg = json.loads(msg)
        return  "result" in jsonmsg and jsonmsg["result"] == "Ok" 


    def SaveMoviePosition(self, mediaId, resumePoint):
            command = '{"jsonrpc":"2.0", "id": 1, "method":"VideoLibrary.SetMovieDetails","params":{"movieid":%d,"resume":{"position":%d,"total":%d}}}' %\
                 (mediaId,resumePoint[0], resumePoint[1])
            return self.ExecuteSavePositionCommand(command)
  
    def SaveEpisodePosition(self, mediaId, resumePoint):
            command = '{"jsonrpc":"2.0", "id":1, "method":"VideoLibrary.SetEpisodeDetails","params":{"episodeid":%d,"resume":{"position":%d,"total":%d}}}' % \
                (mediaId,resumePoint[0], resumePoint[1])
            return self.ExecuteSavePositionCommand(command)
       
    def convertTimeToSeconds(self, jsonTimeElement):
        hours =  int( jsonTimeElement["hours"])
        minutes = int( jsonTimeElement["minutes"])
        seconds = int( jsonTimeElement["seconds"])
        return 3600*hours + 60*minutes + seconds
# -----------------------------------------------------------------------------------------------


if __name__ == '__main__':
    WU = ResumePositionUpdater()
    WU.listen()
    del WU
