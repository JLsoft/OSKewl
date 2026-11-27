# OSKewl
An attempt at an actually-useable-and-decent 'Virtual Keyboard'/On-Screen Keyboard clone of Window's built-in OSK, with hints of the unmatched 'Hacker's Keyboard' from Android, but meant to be used in Linux (mainly Bazzite)



(Preliminary info just to post the keeb)



# Huh?
So, I could only find VERY FEW virtual keyboards for Linux that I could easily get working under Bazzite.  I loved the simplicity and non-ugliness of MS Windows' built-in osk.exe On-Screen Keyboard, and so after using vboard ( https://github.com/mdev588/vboard) and then a later fork of it ( https://github.com/archisman-panigrahi/vboard ) and seeing how they worked and could easily be modified, I decided to set one up how I wanted...and probably nuked most of the original vboard DNA.


# Customization!
OSKewl ('OSK-ewl' -> 'oss-cool' -> ol' skool...you get the idea) is meant to be configurable to the point where you should be able to find a look you want:

- Keyboard can be resized, and keys dynamically change to fit
- Keys can have varying-thickness borders, use any installed font for glyphs, and you can alter the colors for background, keys, borders, and glyphs.
- Translucency sliders for keys and background
- Backgrounds can be 'skinned' with a .png or .jpg and that gets stretched or cropped to fit the keyboard window.
- Keys can also be skinned, but they ALL use a single image in common.  They can also be automatically cut up and/or scaled to fit any of the key sizes with or without gross stretching of the entire image
- Custom key 'click' sound feedback can be enabled, either using one of the included simple sounds, or using your own .wav
- Numpad area can be toggled
- Two layouts to switch between...the original Windows OSK layout, or a more accurate-to-a-physical-keyboard 104 key-ish layout.


# Installation and semi-requirements:
NOTE: This is NOT MEANT to be used in place of Steam's own on-screen keyboard, and so I don't know if it is useable at all for games or anything.

As this was meant for my personal use under Bazzite, and using Plasma, I'm only familiar with what it takes to be ran on there.

1) uinput permissions/rules need set up correctly.  Look a the 'uinput' stuff in the 'vboard' projects above.
2) Run using: python3 OSKewl.py
3) Open the context menu for the OSK's title bar and go to [TO BE CONTINUED]

