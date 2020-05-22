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
    timerThread = [None,None]  # a thread for each player
    running = [False,False]
    updateLock = [threading.RLock(), threading.RLock()] # prevents two thread trying to update the position at the same time


    monitor = xbmc.Monitor()

    def __init__(self):
        self.methodDict = {"Player.OnPause": self.OnPause,
                          "Player.OnPlay": self.OnPlay,
                          "Player.OnResume": self.OnResume,
                          "Player.OnSeek": self.OnSeek,
                          "Player.OnStop": self.OnStop,
                          "System.OnQuit": self.OnQuit,
                          "System.OnRestart": self.OnRestart,
                          }

        self.XBMCIP = addon.getSetting('xbmcip')
        self.XBMCPORT = int(addon.getSetting('xbmcport'))
        
        self.s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.s.setblocking(1)
        xbmc.sleep(int(delay))
        try:
            self.s.connect((self.XBMCIP, self.XBMCPORT))
        except Exception as e:
            xbmc.executebuiltin('Notification(%s, Error: %s, %s, %s)' %(addon_name, str(e), delay, logo) )
            xbmc.sleep(int(delay))
            xbmc.executebuiltin('Notification(%s, Please check JSONRPC settings, %s, %s)' %(addon_name, delay, logo) )
            xbmc.sleep(int(delay))
            exit(0)
                
# -------------------------------- RPC Message handling -----------------------------------------
    def handleMsg(self, msg):
        jsonmsg = json.loads(msg)        
        method = jsonmsg['method']
        xbmc.log("{0} handlemsg {1} ".format(addon_name,str(msg)),xbmc.LOGDEBUG)
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
    def OnSeek(self,jsonmsg):
        updateOnSeek = addon.getSetting('updateonseek') == 'true'
        if ( updateOnSeek ) : self.CommonSaveOnEventProcessing(jsonmsg)
       
    def OnStop(self,jsonmsg):
        self.logEvent(jsonmsg)
        (_,_,playerId) = self.getParameters(jsonmsg)
        self.stopTimer(playerId)

    def OnQuit(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.stopAllTimers()

    def OnRestart(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.stopAllTimers()

    def OnPause(self,jsonmsg):
        self.logEvent(jsonmsg)
        (_,_,playerId) = self.getParameters(jsonmsg)
        self.stopTimer(playerId)
        updateOnPause = addon.getSetting('updateonpause') == 'true'
        if  updateOnPause : self.CommonSaveOnEventProcessing(jsonmsg)
       
    def OnPlay(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
      
    def OnResume(self,jsonmsg):
        self.logEvent(jsonmsg)
        self.handlePlayerStarting(jsonmsg)
 
    def CommonSaveOnEventProcessing(self,jsonmsg):
        (itemid,itemtype,playerid) = self.getParameters(jsonmsg)
        if  self.updateLock[playerid].acquire(blocking=False):
            xbmc.log("{0} thread {1} acquired lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)
            try:
                self.logEvent(jsonmsg)
                position = self.GetPosition(playerid)
                self.SavePosition(itemtype, itemid, position,playerid)
            finally:
                self.updateLock[playerid].release()
                xbmc.log("{0} thread {1} released lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)
        else:
           xbmc.log("{0} thread {1} failed to acquire lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)

  

    def handlePlayerStarting(self,jsonmsg):
        updatePeriodically = addon.getSetting('updateperiodically') == 'true'
        if ( updatePeriodically ): 
            period  = int(addon.getSetting('updateperiod'))       
            (mediaId,mediaType,playerId) = self.getParameters(jsonmsg)
            self.startTimer(period,mediaType,mediaId,playerId)
        else:
            self.stopTimer(playerId)
 
# -------------- periodic update code --------------------------

    # runs on the timerThread to update the position periodically while the player is playing
    # Sleeps in increments of 100ms so the thread can  be quickly an cleanly terminated by setting running false
    # period is based on real time, not on media position. 
    def PeriodicUpdate(self,period,mediaType,mediaId,playerid):
        threadName = threading.current_thread().name
        maxSleep=0.1
        period = max(60,period*60)
        timeRemaining = period
        nextTick = time()+timeRemaining
        self.running[playerid] = True
        try:
            while self.running[playerid]:
                while self.running[playerid] and timeRemaining > 0:
                    timeToSleep = min(maxSleep, timeRemaining)
                    sleep(timeToSleep)
                    timeRemaining = max(0, nextTick-time() )
                    if ( self.monitor.abortRequested() ): self.running[playerid] = False
                if ( self.running[playerid] ):
                    position = self.GetPosition(playerid)
                    xbmc.log("{0} thread {1} invoking SavePosition({2},{3},{4})".format(addon_name,threadName,str(position),mediaType,mediaId),xbmc.LOGDEBUG)
                    self.SavePosition(mediaType,mediaId,position,playerid)  
                    nextTick = nextTick+period
                    timeRemaining = period
            xbmc.log("{0} thread {1} exiting normally".format(addon_name,threadName),xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("{0} thread died due {1} to {2}".format(addon_name,threadName,str(e)),xbmc.LOGDEBUG)
        self.running[playerid] = False
        self.timerThread[playerid] = None
            
    # starts a new periodic timer on the player, destroying the current one if it exists
    def startTimer(self,period,mediaType,mediaId,playerid):        
        if  self.timerThread[playerid] :
            self.stopTimer(playerid)
        xbmc.log("{0} starting thread PeriodicUpdate({1},{2},{3},{4}) ".format(addon_name,str(period),mediaType,str(mediaId),str(playerid)),xbmc.LOGDEBUG)
        self.timerThread[playerid] = threading.Thread(target=self.PeriodicUpdate,args=(period,mediaType,mediaId,playerid))
        self.timerThread[playerid].setName(addon_name+" periodic update for player "+str(playerid))
        self.timerThread[playerid].start()
 
    # destroys the current time thread if it exists
    def stopTimer(self,playerId):
        if  playerId and self.timerThread[playerId] :
            xbmc.log("{0} stopping thread PeriodicUpdate(...) ".format(addon_name),xbmc.LOGDEBUG)
            self.running[playerId] = False
            self.timerThread[playerId].join()
            self.timerThread[playerId] = None

    def stopAllTimers(self):
        for playerId in range(0,2):
            self.stopTimer(playerId)

# ---------------------------------------------------------------------------------
    def getParameters(self,jsonmsg):
        try:
            itemid = jsonmsg["params"]["data"]["item"]["id"]
            itemtype = jsonmsg["params"]["data"]["item"]["type"]
            playerid = int(jsonmsg["params"]["data"]["player"]["playerid"])
            xbmc.log("{0} params itemid: {1} itemtype: {2} playerid: {3}".format(addon_name, str(itemid), itemtype,str(playerid)),xbmc.LOGDEBUG)
            return ( itemid, itemtype, playerid )
        except Exception as e:
             xbmc.log("{0} ignoring event, bad or missing params {1} {2}".format(addon_name, str(jsonmsg), str(e)),xbmc.LOGDEBUG)
        return (None,None,None)
           
    def logEvent(self,  jsonmsg):
         xbmc.log("{0} method: {1} message: {2}".format(addon_name,str(jsonmsg["method"]),str(jsonmsg)),xbmc.LOGDEBUG)

    # save the position to the database (unless another thread is already doing so 
    def SavePosition(self, mediaType, mediaId, position,playerId):
        if self.updateLock[playerId].acquire(blocking=False):
            xbmc.log("{0} thread {1} acquired lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)
            try :
                if mediaType == 'movie':
                    self.SaveMoviePosition(mediaId, position)
                elif mediaType == 'episode':
                    self.SaveEpisodePosition( mediaId, position)
                #TODO: if Kodi ever supports resume position in the database for audio (e.g. audiobook or podcast) handle it here.
                else:
                    xbmc.log("{0} media type {1} not supported by SavePosition)".format(addon_name,mediaType),xbmc.LOGDEBUG)
            finally:
                self.updateLock[playerId].release()
                xbmc.log("{0} thread {1} released lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)
        else:
            xbmc.log("{0} thread {1}failed to acquire lock)".format(addon_name,str(threading.current_thread().name)),xbmc.LOGDEBUG)

    # get the position from the play
    def GetPosition(self, playerid):
        position = None
        try:
            query = '{"jsonrpc":"2.0","method":"Player.GetProperties","params":{"playerid":%d,"properties":["time","totaltime"]},"id":1}' %(playerid)
            xbmc.log("{0} position query for player {1} is  {2} ".format(addon_name,str(playerid),str(query)),xbmc.LOGDEBUG)
            msg = xbmc.executeJSONRPC( query )
            xbmc.log("{0} result of position query for player {1} is  {2} ".format(addon_name,str(playerid),str(msg)),xbmc.LOGDEBUG)
            jsonmsg = json.loads(msg)
            time = self.convertTimeToSeconds(jsonmsg["result"]["time"])
            totalTime = self.convertTimeToSeconds(jsonmsg["result"]["totaltime"])
            position = (time, totalTime)
            xbmc.log("{0} final position is {1} ".format(addon_name,str(position)),xbmc.LOGDEBUG)
            return position
        except Exception as e:
            xbmc.log("{0} failed to determine player position {1} ".format(addon_name,str(e)),xbmc.LOGINFO)


#       xbmc.log("{0} position for player {1} is {2}".format(addon_name, str(playerid), str(position)),xbmc.LOGNOTICE)
        return position


    def SaveMoviePosition(self, mediaId, position):
            command = '{"jsonrpc":"2.0", "id": 1, "method":"VideoLibrary.SetMovieDetails","params":{"movieid":%d,"resume":{"position":%d,"total":%d}}}' %(mediaId,position[0], position[1])
            xbmc.log("{0} save position command {1}  ".format(addon_name,command),xbmc.LOGDEBUG)
            msg = xbmc.executeJSONRPC( command )
            jsonmsg = json.loads(msg)
            xbmc.log("{0} result of position update for is  {1} ".format(addon_name,str(jsonmsg["result"])),xbmc.LOGDEBUG)
 
    def SaveEpisodePosition(self, mediaId, position):
            command = '{"jsonrpc":"2.0", "id":1, "method":"VideoLibrary.SetEpisodeDetails","params":{"movieid":%d,"resume":{"position":%d,"total":%d}}}' %(mediaId,position[0], position[1])
            xbmc.log("{0} save position command {1}  ".format(addon_name,command),xbmc.LOGDEBUG)
            msg = xbmc.executeJSONRPC( command )
            jsonmsg = json.loads(msg)
            xbmc.log("{0} result of position update for is  {1} ".format(addon_name,str(jsonmsg["result"])),xbmc.LOGDEBUG)
     
    def convertTimeToSeconds(self, jsondata):
        hours =  int( jsondata["hours"])
        minutes = int( jsondata["minutes"])
        seconds = int( jsondata["seconds"])
        return 3600*hours + 60*minutes + seconds
# -----------------------------------------------------------------------------------------------


if __name__ == '__main__':
    WU = ResumePositionUpdater()
    WU.listen()
    del WU
