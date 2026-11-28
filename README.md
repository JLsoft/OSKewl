# OSKewl
An attempt at an actually-useable-and-decent 'Virtual Keyboard'/On-Screen Keyboard clone of Window's built-in OSK, with hints of the unmatched 'Hacker's Keyboard' from Android, but meant to be used in Linux (mainly Bazzite)

<img width="882" height="352" alt="WinOSK" src="https://github.com/user-attachments/assets/c958a0a7-e768-4767-9b86-e7d26cc17813" />

Windows stock On-Screen Keyboard



<img width="1242" height="337" alt="OSKewl_custom1" src="https://github.com/user-attachments/assets/3bf92f4f-bb03-4c18-b1f3-6fba0e9820e2" />

OSKewl stock config





# Huh? Whaaaa??
So, I could only find VERY FEW virtual keyboards for Linux that I could easily get working under Bazzite.  I loved the simplicity and non-ugliness of MS Windows' built-in osk.exe On-Screen Keyboard, and I hate phone-style touch keyboard layouts...and so after using vboard ( https://github.com/mdev588/vboard) and then a later fork of it ( https://github.com/archisman-panigrahi/vboard ) and seeing how they worked and could easily be modified, I decided to set one up how I wanted...and probably nuked most of the original vboard DNA.




# Non-obvious features + little touches
- While the key glyphs change to follow and reflect the Shift/CapsLock status, there is an option to force letters to always show as Uppercase or Lowercase


# Customization!
OSKewl ('OSK-ewl' -> 'oss-cool' -> ol' skool...you get the idea) is meant to be configurable to the point where you should be able to find a look you want:

- Keyboard can be resized, and keys dynamically change to fit
- Keys can have varying-thickness borders, use any installed font for glyphs, and you can alter the colors for background, keys, borders, and glyphs.
- Translucency sliders for keys and background
- When using images to skin keys, you can also tint them with a color when they have any non-solid translucency
- Backgrounds can be 'skinned' with a .png or .jpg and that gets stretched or cropped to fit the keyboard window.
- Keys can also be skinned, but they ALL use a single image in common.  They can also be automatically cut up and/or scaled to fit any of the key sizes with or without gross stretching of the entire image
- Custom key 'click' sound feedback can be enabled, either using one of the included simple sounds, or using your own .wav
- NumPad area can be toggled
- You can customize what longer keys (ex: "NumPad", "Options", etc) actually say on them so you can avoid ',,,' abbreviations when resizing if you want, or you can use UNICODE graphical characters (like a making the "Options" key show a Unicode 'Gear' (⚙) character for example)
- Two layouts to switch between...the original Windows OSK layout, or a more accurate-to-a-physical-keyboard 104 key-ish layout.

<img width="1243" height="337" alt="OSKewl_custom0" src="https://github.com/user-attachments/assets/5367d249-6803-4989-96d4-11d8c160e963" />

OSKewl stock WinOSK layout



<img width="1242" height="337" alt="OSKewl_custom1" src="https://github.com/user-attachments/assets/0c92fe6a-20da-410d-8f6f-cd1155d56e39" />

OSKewl stock WinOSK layout with NumPad



<img width="1243" height="409" alt="OSKewl_custom2" src="https://github.com/user-attachments/assets/cb0a9698-dad6-4647-9d70-65a459e1aa20" />

OSKewl '104 key' layout with NumPad



<img width="1599" height="858" alt="OSKewl_custom3" src="https://github.com/user-attachments/assets/fa28b8f5-a7d2-43f9-bacf-9a3a4f6bf5ad" />

OSKewl's Options galore!



<img width="1241" height="381" alt="OSKewl_custom4" src="https://github.com/user-attachments/assets/6842efbe-a18a-4b4b-a849-15c3ec4df53b" />

Simple skinning!



<img width="1580" height="455" alt="OSKewl_custom5" src="https://github.com/user-attachments/assets/628e4d6f-b856-4dab-926f-60601723f603" />

Make it look however you want, oof...






# Installation and semi-requirements:
NOTE: This is NOT MEANT to be used in place of Steam's own on-screen keyboard, and so I don't know if it is useable at all for games or anything.
NOTE ALSO: It can not be used to log into the system



As this was meant for my personal use for interacting with the desktop under Bazzite (using Plasma), I'm only familiar with what it takes to be ran on there. No guarantees that you won't run into any problems with your setup

1) uinput permissions/rules need set up correctly.  Look at the 'uinput' stuff needed in the installation instructions of the 'vboard' projects linked to at the top of this readme.
2) Just grab `OSKewl.py` from this repo
3) Run using: python3 OSKewl.py
 
(You can easily make it a shortcut...place OSKewl.py in your home folder, on your desktop create OSKewl.desktop and make the contents:

```
[Desktop Entry]
Categories=Utility
Comment[en_US]=
Comment=
Exec=bash -c 'python3 ~/OSKewl.py'
GenericName[en_US]=
GenericName=
Icon=input-keyboard-virtual-on
MimeType=
Name[en_US]=OSKewl
Name=OSKewl
NoDisplay=false
Path=
StartupNotify=true
Terminal=false
TerminalOptions=
Type=Application
X-KDE-SubstituteUID=false
X-KDE-Username=
```
...and you can drag the resulting shortcut to your taskbar, and then should be able to just click it to open the keyboard)


4) Open the context menu for the OSK's title bar and go to `More Actions > Configure Special Window Settings...`
<img width="691" height="377" alt="OSKewl_howto1" src="https://github.com/user-attachments/assets/e1245ee5-34ff-429c-a3c4-0ca8bf9bcf19" />

5) Go to `Add Property...` and add `Keep above other windows` - Set to "Force", and select "Yes"
6) Go to `Add Property...` and add `Accept focus` - Set to "Force", and select "No"
<img width="676" height="713" alt="OSKewl_howto2" src="https://github.com/user-attachments/assets/9b6a8055-3041-47e7-a0f7-c9ebc0d56f3b" />




# Troublehooting
Settings are stored in `~/.config/oskewl`, in `settings.conf`
You can manually edit or delete if something breaks bad enough to prevent you from entering the Options menu.



