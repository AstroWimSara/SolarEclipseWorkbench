- Go/no-go panel at T−30 min. Run the Verify with Camera... checks (battery, card space for the script's frame count, mode dial, focus mode, clock) from the main window right before C1, with one clear green or red result.

- Sort the images. Download or rename the images by the script line that took them (phase, label, bracket or HDR group) into folders ready for stacking. Building on that, add the timelapse alignment script (#70).

- INDI mount control (#75). Connect to the telescope mount through an INDI server (local, in WSL on Windows, or on a separate machine such as a Raspberry Pi at the mount), so the run can keep the sun in the field of view. Astro cameras are out of scope; the DSLRs stay on gphoto2.
  1. Connect to the mount, switch on solar tracking at the start of a run, and park it at the end (optional).
  2. Manual nudge buttons (N/S/E/W) in the live view window and on the phone dashboard.
  3. Automatic re-centering from the DSLR live view: fit a circle to the sun's limb (not the crescent's centroid), send small pulse-guide corrections only between scheduled exposures, and pause from 15 s before C2 to 15 s after C3, like live view does.