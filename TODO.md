## TODO

### GPS

- [ ] Get GPS coordinates from device
- https://github.com/quentinsf/pygarmin
  
### GUI

### Scripts

### Camera

- [ ] Mirror up - TEST???
- [ ] All commands from Solar Eclipse Maestro: http://xjubier.free.fr/en/site_pages/solar_eclipses/Solar_Eclipse_Maestro_Help/pgs2/btoc6.html

### Notifications 

- [ ] Sound does not work in wsl
  - [ ] Known problem, we should remove the voice_prompt commands from the scheduler

### Problems with gphoto2

- [ ] Camera access only works when executing the command using `sudo`

Hi,
Im not familiar with the ptpcamerad process and stuff so the following solution might need a clear review before use.

-Save this as a .plist file in /Library/LaunchDaemons/ (open -a Finder /Library/LaunchDaemons/)


<?xml version="1.0" encoding="UTF-8"?>
 <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
 <plist version="1.0">
 <dict>
     <key>Label</key>
     <string>com.example.ptpcamerad</string>
     <key>Program</key>
     <string>/usr/bin/ptpcamerad</string> 
     <key>RunAtLoad</key>
     <true/>
     <key>KeepAlive</key>
     <false/>
</dict>
 </plist>

Be sure to replace /usr/bin/ptpcamerad with your actual path of ptpcamerad (ps aux | grep ptpcamerad retrieves it)

In terminal
sudo chown root:wheel /Library/LaunchDaemons/com.example.ptpcamerad.plist
sudo chmod 644 /Library/LaunchDaemons/com.example.ptpcamerad.plist
To set permissions

In terminal
sudo launchctl load /Library/LaunchDaemons/com.example.ptpcamerad.plist

So basically what it does it sets the property KeepAlive of ptpcamera to False which prevents the process to respawn when killed. You can know kill it once (still spawns once when your computer boots) and you should be fine.

Again, i'm not familiar with this stuff. I found this solution thanks to chatgpt and it works for me. So if you find any issues or reason not to do it please let us know.