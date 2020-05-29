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




addon = xbmcaddon.Addon('service.position.updater')
addon_name = addon.getAddonInfo('name')

delay = '4000'
logo = 'special://home/addons/service.position.updater/icon.png'


class ResumePositionUpdater():
    onStopAccuracy = 5
    monitor = xbmc.Monitor()

    def __init__(self):
        self.methodDict = {"Player.OnPause": self.OnPause,
                          "Player.OnPlay": self.OnPlay,
                          "Player.OnResume": self.OnResume,
                          "Player.OnSeek": self.OnSeek,
                          "Player.OnStop": self.OnStop,
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
                    xbmc.log('% count not read advancedsettings.xml %s' % (addon_name,str(e)),xbmc.LOGDEBUG)
                    pass
            self.advancedSettingsFileProcessed = True

    def GetKodiAdvancedSettingInt(self,name,default):
        return int(self.GetKodiAdvancedSetting(name,default))

    def GetKodiAdvancedSetting(self,name,default):
        result = default
        self.LoadAdvancedSettingsDom()
        if self.advancedSettingsFileDom:
            root = self.advancedSettingsFileDom.getroot()
            xbmc.log("%s root is %s" % (addon_name,str(root)),xbmc.LOGDEBUG)
            child = root.find(name)
            xbmc.log("%s child %s is %s" % (addon_name,name,str(child)),xbmc.LOGDEBUG)
            if child is not None:
                result = child.text

        xbmc.log("%s final result is %s" % (addon_name,str(result)),xbmc.LOGDEBUG)
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
        def __init__(self, playerid):
            self.playerid = playerid

        def __str__(self):
            return 'PlayerState{playerid=%d,running=%s,handleOnStop=%s,mediaType=%s,mediaId=%d,position=%s,file=%s}'% \
                (self.playerid,self.running,self.handleOnStop,self.mediaType,self.mediaId,self.position,self.playingFile)
        def __repr__(self):
            return self.__str__()

    player = [PlayerState(0),PlayerState(1)]
  
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
        updateNfoOnSeek = addon.getSetting('updatenfoonseek') == 'true'
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        if ( updateOnSeek ) : self.CommonSaveOnEventProcessing(playerState,jsonmsg,updateOnSeek,updateNfoOnSeek)
       
    def OnStop(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
        playerState.handleOnStop = True
        self.stopTimer(playerState)

    def OnPause(self,jsonmsg):
        self.logEvent(jsonmsg)
        playerState = self.selectPlayerStateForMessage(jsonmsg)
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
 
    def CommonSaveOnEventProcessing(self,playerState,jsonmsg,saveToDb,saveToNfo):
        self.logEvent(jsonmsg)
        playerState.position = self.GetPosition(playerState.playerid)
        self.CommonSaveProcessing(playerState,saveToDb,saveToNfo)
 
    def CommonSaveProcessing(self,playerState,saveToDb,saveToNfo):
        if  playerState.updateLock.acquire(blocking=False):
            xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
            try:
                if self.PositionInRange(playerState.position):
                    if saveToDb:self.SavePositionToDb(playerState)
                    if saveToNfo:self.SavePositionToNfo(playerState)
                else:
                    if saveToDb:self.RemovePositionElementFromNfo(playerState)
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
            (mediaId,mediaType,playerId) = self.getParameters(jsonmsg)
            playerState = self.player[playerId]
            if playerState.mediaId != mediaId or playerState.mediaType != mediaType:
                playerState.mediaId = mediaId
                playerState.mediaType = mediaType
                playerState.playingFile=xbmc.player[playerState].getPlayingFile()
            return playerState
 

    def handlePlayerStarting(self,jsonmsg):
        (mediaId,mediaType,playerId) = self.getParameters(jsonmsg)
        playerState = self.player[playerId]
        playerState.mediaId = mediaId
        playerState.mediaType = mediaType

        tasks = list()
        now = time()
        if addon.getSetting('updateperiodically') == 'true':
            period  = int(addon.getSetting('updateperiod'))       
            task=self.TimerTask("Update Db for player"+str(playerState.playerid), \
                playerState,period,self.SaveToDbPeriodicallyTask,now)
            tasks.append(task)
        if addon.getSetting('updatenfoonstop') == "true":
            task=self.TimerTask("Remember Position for OnStop player"+str(playerState.playerid),  \
                playerState,self.onStopAccuracy,self.SavePositionForOnStop,now)
            tasks.append(task)

        if ( tasks ): 
            self.startTimer(playerState,tasks)
        else:
            self.stopTimer(playerState)

    def SavePositionForOnStop(self,playerState):
        xbmc.log('%s SavePositionForOnStop(%s)' % (addon_name, playerState),xbmc.LOGDEBUG)
        pass

    def SaveToDbPeriodicallyTask(self,playerState):
        if self.PositionInRange(playerState.position):
            xbmc.log('%s thread %s on period invoking\1SavePositionToDb\2%s,%s,%d) ' \
                    % (addon_name,threading.currentThread().name,str(playerState.position), \
                        playerState.mediaType,playerState.mediaId), \
                xbmc.LOGDEBUG)
            self.SavePositionToDb(playerState) 
            self.CommonSaveProcessing(playerState,True,False)
            
    def PositionInRange(self,position):
        xbmc.log('%s PositionInRange(%s) ignoresecondsatstart=%s ignorepercentatend=%s' % (addon_name,str(position),str(self.ignoresecondsatstart),str(self.ignorepercentatend)),xbmc.LOGDEBUG)
        if not position or position[0] < self.ignoresecondsatstart: return False
        percentComplete = 100.0 * position[0] / position[1]
        xbmc.log('%s  %f <= %f' % (addon_name,percentComplete,100.0-self.ignorepercentatend),xbmc.LOGDEBUG)
        return percentComplete <= 100.0-self.ignorepercentatend


 
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
                self.nextTime = now+self.period # way off, rebaseline our ticks

        def __str__(self):
            return "TimerTask{name=%s,period=%d,nextTime=%f,state=%s}"  % \
                 (self.name, self.period, self.nextTime,self.playerState)

        def __repr__(self):
            return self.__str__()

    def NextTick(self,tasks,lastTick):
        xbmc.log("NextTick(%s,%s)" %(tasks,lastTick),xbmc.LOGDEBUG)
        now = time()
        nextTime = now+24*60*60
        for task in tasks: nextTime = min(nextTime, task.nextTime)
        xbmc.log("%f=NextTick(%s,%s)" %(nextTime,tasks,lastTick),xbmc.LOGDEBUG)
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
                    if ( abortRequested ): 
                        playerState.running = False
                        xbmc.log('%s thread %s abort request received' % \
                            (addon_name,threadName), \
                                xbmc.LOGDEBUG)
                # we're at t nextTick, execute any tasks that are ready to go
                if ( not abortRequested and playerState.running ):
                    playerState.position = self.GetPosition(playerState.playerid)
                    for task in tasks:
                        xbmc.log("%s" % (task),xbmc.LOGDEBUG)
                        if task.nextTime <= now :
                            xbmc.log('%s  thread %s executing %s '  \
                                 % (addon_name,playerState.timerThread.name,task.name),  \
                                   xbmc.LOGDEBUG)
                            task.callback(playerState)
                            task.computeNextTime(now)
                            xbmc.log("task.nextTime=%f" %(task.nextTime),xbmc.LOGDEBUG)
            # thread is stopping
            updateNfoOnStop = addon.getSetting('updatenfoonstop') == "true"
            if ( not abortRequested and updateNfoOnStop and playerState.handleOnStop ):
                xbmc.log('%s thread %s saving to NFO on stop' % \
                            (addon_name,threadName), \
                                xbmc.LOGDEBUG)
                if addon.getSetting('removeonendofmedia') == 'true' and \
                        playerState.position and \
                        playerState.position[0] / playerState.position[1] * 100.0 >= 100.0 - self.ignorepercentatend:
                    self.RemovePositionElementFromNfo(playerState) 
                else:
                    self.SavePositionToNfo(playerState)
            xbmc.log('%s thread %s exiting normally' % (addon_name,threadName),\
                xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("%s thread died due %s to %s" % \
                  (addon_name,threadName,str(e)),  \
                      xbmc.LOGDEBUG)
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
        xbmc.log('%s starting thread %s  '  \
               % (addon_name,playerState.timerThread.name),  \
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

    def SavePositionToNfo(self,playerState):
        xbmc.log("%s thread %s SavePositionToNfo(%s)" % (addon_name,threading.current_thread().name,playerState),xbmc.LOGDEBUG)
       
    # save the position to the database (unless another thread is already doing so 
    def SavePositionToDb(self, playerState):
        if playerState.updateLock.acquire(blocking=False):
            xbmc.log("%s thread %s acquired lock" % (addon_name,threading.current_thread().name),xbmc.LOGDEBUG)
            try :
                if playerState.mediaType == 'movie':
                    self.SaveMoviePosition(playerState.mediaId, playerState.position)
                elif playerState.mediaType == 'episode':
                    self.SaveEpisodePosition( playerState.mediaId, playerState.position)
                elif playerState.mediaType == 'song':
                    pass
                #   self.SaveSongPosition( mediaId, position)
                else:
                    pass
                    xbmc.log("%s media type %s not known by SavePositionToDb)" % (addon_name,playerState.mediaType),xbmc.LOGDEBUG)
            finally:
                playerState.updateLock.release()
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

    def RemovePositionElementFromNfo(self,playerState):
        xbmc.log('RemovePositionElementFromNfo(%s)' %(playerState),xbmc.LOGDEBUG)


if __name__ == '__main__':
    WU = ResumePositionUpdater()
    WU.listen()
    del WU
