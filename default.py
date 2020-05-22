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
import xbmcvfs
import xbmcaddon
import socket
import json
import xml.etree.ElementTree as ET
from os import path
from os import stat as osstat
import threading
from time import sleep
from time import time



addon = xbmcaddon.Addon('service.position.updater')
addon_name = addon.getAddonInfo('name')

delay = '4000'
logo = 'special://home/addons/service.position.updater/icon.png'





class ResumePositionUpdater():
    timerThread = None
    updateLock = threading.RLock()
    running = False
    def __init__(self):
        self.methodDict = {"Player.OnPause": self.OnPause,
                          "Player.OnPlay": self.OnPlay,
                          "Player.OnResume": self.OnResume,
 #                         "Player.OnPropertyChanged": self.OnPropertyChanged,
                          "Player.OnSeek": self.OnSeek,
 #                         "Player.OnSpeedChanged": self.OnSpeedChanged,
                          "Player.OnStop": self.OnStop,
 #                         "Player.OnAVChange": self.OnAVChange,
 #                         "Player.OnAVStart": self.OnAVStart,
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
                

    def handleMsg(self, msg):
        jsonmsg = json.loads(msg)        
        method = jsonmsg['method']
        xbmc.log("{0} handlemsg {1} ".format(addon_name,str(msg)),xbmc.LOGNOTICE)
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


    def getParameters(self,jsonmsg):
        try:
            itemid = jsonmsg["params"]["data"]["item"]["id"]
            itemtype = jsonmsg["params"]["data"]["item"]["type"]
            playerid = jsonmsg["params"]["data"]["player"]["playerid"]
            xbmc.log("{0} params itemid: {1} itemtype: {2} playerid: {3}".format(addon_name, str(itemid), str(itemtype),str(playerid)),xbmc.LOGDEBUG)
            return ( itemid, itemtype, playerid )
        except Exception as e:
             xbmc.log("{0} ignoring event, bad or missing params {1} {2}".format(addon_name, str(jsonmsg), str(e)),xbmc.LOGDEBUG)
        return (None,None,None)
           
    def logEvent(self, eventname, jsonmsg):
         xbmc.log("{0} event: {1} message: {2}".format(addon_name,str(eventname),str(jsonmsg)),xbmc.LOGDEBUG)
 
    def SaveResumePosition(self,messageType,jsonmsg):
        if ( self.updateLock.acquire(blocking=False)):
            self.logEvent(messageType,jsonmsg)
            (itemid,itemtype,playerid) = self.getParameters(jsonmsg)
            position = self.GetPosition(playerid)
            self.SavePosition(itemtype, itemid, position)
       
    def SavePosition(self, mediaType, mediaId, position):
        if self.updateLock.acquire(blocking=False):
            if mediaType == 'movie':
                self.SaveMoviePosition(mediaId, position)
            if mediaType == 'episode':
                self.SaveEpisodePosition( mediaId, position)
            #TODO: if Kodi ever supports resume position in the database for audio (e.g. audiobook or podcast) handle it here.
 

    def OnPause(self,jsonmsg):
        self.stopTimer()
        updateOnPause = addon.getSetting('updateonpause') == 'true'
        if ( updateOnPause ) : self.SaveResumePosition("Player.OnPause",jsonmsg)
       
    def OnPlay(self,jsonmsg):
        self.logEvent("Player.OnPlay",jsonmsg)
        self.handlePlayerStarting(jsonmsg)
      
    def OnResume(self,jsonmsg):
        self.logEvent("Player.OnPlay",jsonmsg)
        self.handlePlayerStarting(jsonmsg)

    def handlePlayerStarting(self,jsonmsg):
        updatePeriodically = addon.getSetting('updateperiodically') == 'true'
        if ( updatePeriodically ): 
            period  = min(1,int(addon.getSetting('updateperiod'))) * 60       
            (mediaId,mediaType,playerId) = self.getParameters(jsonmsg)
            self.startTimer(period,mediaType,mediaId,playerId)
        else:
            self.stopTimer()
 
       
    def OnSeek(self,jsonmsg):
        updateOnSeek = addon.getSetting('updateonseek') == 'true'
        if ( updateOnSeek ) : self.SaveResumePosition("Player.OnSeek",jsonmsg)
       
    def OnStop(self,jsonmsg):
        self.logEvent("Player.OnStop",jsonmsg)

    def PeriodicUpdate(self,period,mediaType,mediaId,playerid):
        maxSleep=0.1
        timeRemaining = period
        nextTick = time()+timeRemaining
        self.running = True
        try:
            while self.running:
                while self.running and timeRemaining > 0:
                    timeToSleep = min(maxSleep, timeRemaining)
                    sleep(timeToSleep)
                    timeRemaining = max(0, nextTick-time() )
                xbmc.log("{0} thread PeriodicUpdate(...) invoking SavePosition".format(addon_name),xbmc.LOGDEBUG)
                position = self.GetPosition(playerid)
                self.SavePosition(position,mediaType,mediaId)  
                nextTick = nextTick+period
                timeRemaining = period
            xbmc.log("{0} thread PeriodicUpdate(...) exiting normally".format(addon_name),xbmc.LOGDEBUG)
        except Exception as e:
            xbmc.log("{0} PeriodicUpdate thread died due to {1}".format(addon_name,str(e)),xbmc.LOGDEBUG)
        self.running = False
        self.timerThread = None
            
       
    def startTimer(self,period,mediaType,mediaId,playerid):
        
        if ( self.timerThread ):
            self.stopTimer()
        xbmc.log("{0} starting thread PeriodicUpdate({1},{2},{3},{4}) ".format(addon_name,str(period),mediaType,str(mediaId),str(playerid)),xbmc.LOGDEBUG)
        self.timerThread = threading.Thread(target=self.PeriodicUpdate,args=(period,mediaType,mediaId,playerid))
        self.timerThread.start()
 
    def stopTimer(self):
        if ( self.timerThread ):
            xbmc.log("{0} stopping thread PeriodicUpdate(...) ".format(addon_name),xbmc.LOGDEBUG)
            self.running = False
            self.timerThread.join()
            self.timerThread = None

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
            xbmc.log("{0} result of position update for is  {1} ".format(addon_name,msg),xbmc.LOGINFO)
            xbmc.log("{0} result of position update  is  {1} ".format(addon_name,str(jsonmsg["result"])),xbmc.LOGDEBUG)

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
        return 3600*hours + 60*minutes+seconds



if __name__ == '__main__':
    WU = ResumePositionUpdater()
    WU.listen()
    del WU
