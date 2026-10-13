# Solar Eclipse Workbench Configuration Wizard Guide

## Overview

The SEW Configuration Wizard (`sew_wizard`) is a graphical user interface tool that helps you create photography scripts for solar eclipse observations. It provides an intuitive, step-by-step interface for configuring your eclipse photography session.

## Features

- **User-friendly GUI**: Modern PyQt6-based interface with step-by-step wizard
- **Eclipse Configuration**: Select from upcoming eclipses and locations
- **Equipment Setup**: Configure camera name, solar filter settings, and camera sync options
- **ISO Configuration**: Set preferred ISO and bracketing range for optimal exposures
- **Automatic Exposure Calculation**: Calculates optimal camera settings based on sun altitude, observer elevation, and equipment specifications
- **Phenomena Selection**: Choose which eclipse phenomena to photograph
- **Voice Prompts**: Optional basic or extended voice prompts
- **Camera Synchronization**: Periodic camera monitoring for battery and disk space
- **Configuration Persistence**: Save and reuse camera and location configurations
- **Script Generation**: Automatically generates a script file compatible with Solar Eclipse Workbench

## Installation

The wizard is installed automatically with Solar Eclipse Workbench. After installation, the `sew_wizard` command should be available in your environment.

```bash
# Install using poetry
poetry install

# Or using pip
pip install -e .
```

## Running the Wizard

### From Command Line

```bash
# If installed via poetry
poetry run sew_wizard

# Or if scripts are in your PATH
sew_wizard
```

### From Python

```python
from solareclipseworkbench.wizard import main
main()
```

## Wizard Pages

### 1. Introduction

Welcome page explaining the wizard's purpose and what you'll configure.

### 2. Eclipse Configuration

Configure eclipse information and observation location:

#### Eclipse Selection
Select from upcoming solar eclipses:
- **Eclipse Dropdown**: Shows the next 20 solar eclipses with date, type, and duration/magnitude
- **Automatic Details**: Date, type, and magnitude are automatically filled based on selection
- Eclipse data is loaded from the Solar Eclipse Workbench database

The wizard displays eclipses in the format:
- Total/Annular/Hybrid: "DD/MM/YYYY - Type - Duration (Xm XXs)"
- Partial: "DD/MM/YYYY - Type - Magnitude%"

#### Location Selection
Choose your observation location:
- **Location Dropdown**: Select from your saved custom locations or choose "Custom" to create a new one
- **Saved Custom Locations**: Your previously saved observation locations (marked with "(Saved)")
- **Custom Location**: Enter your exact coordinates manually and save for future use

When selecting a saved location, coordinates are automatically filled.
When selecting "Custom", you must enter:
- **Location Name**: (Optional) Name this location to save it for future use
- **Longitude**: -180° to 180° (East: positive, West: negative)
- **Latitude**: -90° to 90° (North: positive, South: negative)  
- **Altitude**: Height above sea level in meters
- **Save Location Button**: Click to save this custom location for future wizard sessions

**Tip**: Save all your observation sites (your backyard, favorite dark sky location, travel destinations, etc.) to quickly access them in future sessions. The wizard remembers your last used location and automatically selects it when you start the wizard.


### 3. Equipment Configuration

Set up your camera and filter equipment:

#### Camera Selection
Choose or configure your camera:
- **Camera Dropdown**: Select from previously saved cameras or choose "New Camera..." to configure a new one
- **Saved Cameras**: All your previously saved camera configurations
- **New Camera**: Configure a new camera with all specifications

When you select a saved camera, all camera details (name, focal length, aperture range, filter ND value) are automatically loaded. The wizard remembers your last used camera for convenience.

#### Camera Details
Configure your camera specifications:

**Camera Name**: Enter your camera model name exactly as it appears in the camera system (e.g., "Canon EOS 80D", "Nikon D850"). This name will be used in all generated commands.  It must be the exact name recognized by the Solar Eclipse Workbench camera system to ensure proper command generation.

**Save Camera Button**: Click to save your current camera configuration (name, lens specs, filter) for future wizard sessions. Saved cameras appear in the Camera Selection dropdown.

#### Test Camera
Connect the camera via USB with the lens (or telescope) you will use, close Solar Eclipse Workbench if it is running, and click **Test Camera...**.  Best do this before generating the script: the script is then fitted to this camera.

- **Check Settings** only reads from the camera: the shutter speeds, ISO values and apertures it offers with the mounted lens, whether it can shoot continuous bursts over USB, and its state (mode dial, focus, battery, card space, auto power off, clock).
- **Full Test** also sets the camera clock and checks the result, and takes a test picture and a test burst (saved on the memory card) to measure how long the camera needs for them.

The result is saved with the camera configuration (save the camera to keep it), so the test is only needed once per camera and lens; repeat it when you change the lens.  When the script is generated for a tested camera:

- every exposure is fitted to the settings the camera really offers, keeping the brightness the same.  For example, 1/8000 s on a camera that stops at 1/4000 s becomes 1/4000 s at a lower ISO or with the lens stopped down one stop, within the ISO and aperture range set on this page.  An aperture the lens does not have is replaced by the nearest one.  When no allowed setting gives the planned exposure, the shot is marked "camera limit" in its description, with the number of stops it will be over- or underexposed;
- the diamond ring, Baily's beads, contact, earthshine and HDR shots are spaced by the measured durations instead of the estimates.

Without a test, the script uses standard shutter speeds and estimated durations, as before.

#### Lens/Telescope Configuration
Specify your optical equipment specifications:
- **Focal Length**: Set the focal length in millimeters (10-5000mm range, default 400mm)
  - For prime lenses: Enter the fixed focal length
  - For zoom lenses: Enter the focal length you plan to use
  - For telescopes: Enter the telescope's focal length
- **Aperture Range**: Set the minimum and maximum f-numbers (1.0-64.0 range)
  - For prime lenses: Set both min and max to the same value (e.g., f/2.8)
  - For zoom lenses: Set the range (e.g., f/3.5 min to f/5.6 max)
  - For telescopes: Set based on your telescope's specifications

**Note**: These specifications are crucial for calculating correct exposure settings for different eclipse phases, particularly for the corona where settings vary significantly based on focal length.

#### ISO Settings
Configure your camera's ISO settings for automatic exposure calculation:
- **Preferred ISO**: Your preferred ISO value for eclipse photography (100-6400)
  - Lower values (100-400): Better image quality, less noise, but requires longer exposures
  - Higher values (800-3200): Shorter exposures, but more noise in images
  - Recommended: ISO 400 for most eclipse photography
- **ISO Range (for bracketing)**: Minimum and maximum ISO values for exposure bracketing suggestions
  - The wizard uses this range to suggest alternative ISO settings if needed
  - **Preferred ISO** is used for all exposure calculations in the generated script

**Exposure Calculation**: The wizard automatically calculates optimal camera settings (shutter speed, aperture, ISO) for each eclipse phenomenon based on:
- **Sun altitude angle**: Higher sun = brighter = faster shutter speeds
- **Observer altitude**: Elevation above sea level affects atmospheric extinction
- **Camera ISO**: Doubling ISO halves the required exposure time
- **Lens aperture**: Each f-stop change doubles/halves exposure time
- **Solar filter ND value**: For partial phases (ND5.0 or ND4.0)

These calculations are based on scientifically validated exposure data from Xavier Jubier's eclipse exposure calculator, ensuring optimal image quality for each phenomenon from partial eclipse through totality.

#### Solar Filter ND Value
Select the Neutral Density value of your full-aperture solar filter:
- **5.0**: Common ND5 filters (100,000x reduction)
- **3.8**: Baader Photography solar filters
- **Manual**: Enter a custom ND value if your filter doesn't match the presets

#### Voice Prompts
Enable audio prompts during your eclipse observation:
- **Disabled**: No voice prompts
- **Basic**: Essential prompts only (contacts, totality)
- **Extended**: Comprehensive prompts with countdowns and status updates

#### Camera Synchronization
Enable periodic camera synchronization to monitor equipment status:
- **Purpose**: Checks battery level and available disk space on your camera
- **Scheduling**: Sync commands are placed during gaps between photography commands (when there is at least 10 seconds of free time)
- **Intervals**: Choose from 5, 15, or 30 minutes
  - **5 minutes**: Frequent monitoring, recommended for long eclipses or if battery/storage is a concern
  - **15 minutes**: Balanced monitoring (default)
  - **30 minutes**: Less frequent, suitable for shorter eclipses

**Note**: Sync commands are scheduled approximately every X minutes, but not exactly. The wizard places them during natural gaps in your photography sequence to avoid interfering with critical moments. This ensures you don't miss important phenomena while still keeping track of your camera's status.

### 4. Phenomena Selection

Choose which eclipse phenomena to photograph:

#### Available Phenomena
- **First (C1) and Fourth (C4) Contacts**: Beginning and end of partial eclipse
- **Equispaced Shots During Partial Phases**: Regular interval shots with solar filter
- **Diamond Rings (C2 and C3)**: Just before/after totality
- **Baily's Beads**: Beautiful beading effect at C2/C3
- **Chromosphere**: Sun's chromosphere visible briefly at C3
- **Solar Corona**: During totality (with adjustable step interval)

#### Partial Eclipse Interval
Configure how often to take photos during partial phases:
- **By Magnitude**: Take photos every X% of eclipse magnitude (e.g., every 2%)
  - The wizard calculates the approximate number of shots based on 100% / interval
  - Shots are distributed evenly across the C1-C2 and C3-C4 durations
- **By Time**: Take photos every X seconds (e.g., every 60 seconds)
  - The wizard calculates exactly how many shots fit in the C1-C2 and C3-C4 durations
  - Each shot is precisely timed with calculated sun altitude and optimal exposure

**Automatic Partial Phase Generation**: When you enable "Equispaced Shots During Partial Phases", the wizard generates ALL intermediate photography commands between C1-C2 and C3-C4, not just examples. For each shot:
- **Precise Timing**: Calculated from actual eclipse reference moments (C1, C2, C3, C4)
- **Sun Altitude**: Calculated for the exact time of each shot
- **Optimal Exposure**: Shutter speed calculated based on sun altitude at that moment
- **Auto-ISO Adjustment**: If sun gets low and shutter speed becomes too slow (> 1/30s), ISO is automatically increased up to your maximum ISO setting

**Example**: For a 55-minute C1-C2 partial phase with 60-second intervals:
- 55 individual `take_picture` commands are generated
- Each shows the exact UTC time, sun altitude, and calculated shutter speed
- As sun altitude drops from 18° to 8°, shutter speeds automatically adjust from 1/4147s to 1/1779s
- All shots stay at preferred ISO 400 (fast enough throughout)

**Example Script Output**:
```
# Partial phase (C1 to C2) - with solar filter
# Shots every 60 seconds
#
take_picture, C1, +, 0:0:00.0, Canon EOS 80D, 1/4147, 5.6, 400, "Partial C1-C2 #1 @ 17:34:34, sun 18.4°"
take_picture, C1, +, 0:1:00.0, Canon EOS 80D, 1/4133, 5.6, 400, "Partial C1-C2 #2 @ 17:35:34, sun 18.2°"
take_picture, C1, +, 0:2:00.0, Canon EOS 80D, 1/4119, 5.6, 400, "Partial C1-C2 #3 @ 17:36:34, sun 18.0°"
...
take_picture, C1, +, 0:54:00.0, Canon EOS 80D, 1/1779, 5.6, 400, "Partial C1-C2 #55 @ 18:28:34, sun 8.4°"
```

This ensures you capture the complete eclipse progression with scientifically accurate exposures at every moment.

### 5. Summary and Generation

Review your configuration and generate the script:

#### Summary Display
Shows all your configured settings for final review.

#### Script Preview
Displays the generated script content before saving.

#### Save Location
Choose where to save your generated script file. Default location is your home directory with an auto-generated filename.

#### Verify with Camera
A final check of the generated script with the camera connected (**Verify with Camera...**).  It checks that the camera name in the script matches the connected camera (otherwise SEW skips every command for it), that every ISO, shutter speed and aperture of the script is available, the camera state, and whether the commands follow each other slowly enough for this camera.  The full test also sets and verifies the clock and times a test picture and a test burst.  The result is shown as a list with a check mark, note, warning or cross per item, and is also written to the log file.

The summary at the top of this page already shows whether the script was fitted to a tested camera, and the result of the timing check of the generated script.

## Generated Script Format

The wizard generates a `.txt` script file compatible with Solar Eclipse Workbench containing:

- Header comments with eclipse and equipment information
- Voice prompt references (if enabled)
- Photography commands for selected phenomena
- Timing based on eclipse contacts (C1, C2, MAX, C3, C4)

### Example Generated Commands

```
# First contact (C1)
take_picture, C1, -, 0:00:02.0, Canon EOS 80D, 1/4000, 8, 200, "First contact (C1-2s)"
take_picture, C1, +, 0:00:00.0, Canon EOS 80D, 1/4000, 8, 200, "First contact (C1)"

# Diamond ring and Baily's beads (C2)
take_burst, C2, -, 0:00:05.0, Canon EOS 80D, 1/1000, 5.6, 400, 3, "Pre-C2 diamond/beads"

# Totality - Solar Corona
take_bracket, C2, +, 0:00:05.0, Canon EOS 80D, 1/1000, 5.6, 400, "+/- 2", "Corona bracket 1"

# Camera synchronization (if enabled)
sync_cameras, C2, -, 0:30:00.0, "Camera sync (30 min before C2)"
sync_cameras, C2, -, 0:15:00.0, "Camera sync (15 min before C2)"
```

**Note**: Camera sync commands are scheduled during free time between photography commands and check battery level and available disk space.

### Exposure Calculation Details

The wizard automatically calculates optimal exposure settings for each eclipse phenomenon. After you complete the wizard, the generated script includes a detailed exposure calculation summary in its header comments, showing the calculated shutter speeds for each phenomenon based on your specific circumstances.

**Example Exposure Calculation Output**:
```
# Calculated Exposures (ISO 400, f/5.6):
# ------------------------------------------------
#   partial_c1               :     1/2032  (sun alt:  18.4°)
#   partial_c4               :       1.7s  (sun alt:  -1.3°)
#   bailys_beads_c2          :      1/282  (sun alt:   8.2°)
#   chromosphere_c2          :      1/141  (sun alt:   8.2°)
#   corona_lower             :       1/18  (sun alt:   8.0°)
#   corona_middle            :        1/1  (sun alt:   8.0°)
#   corona_upper             :       1.2s  (sun alt:   8.0°)
```

These calculated values are then used throughout the script for each photography command, ensuring scientifically accurate exposures tailored to your exact eclipse circumstances.

**Calculation Method**:
The exposure calculator uses a comprehensive 2D interpolation system based on:
1. **Sun Altitude Angle** (0°-60°): Primary factor - higher sun = less atmospheric extinction = faster shutter
2. **Observer Altitude** (0-3000m above sea level): Secondary factor - higher elevation = thinner atmosphere
3. **Eclipse Phenomenon**: Each phenomenon (partial, Baily's beads, chromosphere, corona layers) has different brightness
4. **Camera Settings**: ISO, aperture, and ND filter adjustments

The base exposure data comes from Xavier Jubier's scientifically validated eclipse exposure calculator (http://xjubier.free.fr), ensuring professional-quality results.

## Using the Generated Script

1. **Save the script** to a location you can easily access
2. **Open Solar Eclipse Workbench** main application
3. **Load the script** using the job scheduling functionality
4. **Review the exposure calculations** in the script header to understand your camera settings
5. **Test before the eclipse** to ensure everything works correctly

## Camera Settings in Generated Scripts

The wizard generates commands with **automatically calculated** camera settings optimized for:
- Your specific eclipse date and location
- Your observation altitude above sea level
- The sun's altitude angle at each eclipse phase
- Your camera's ISO setting
- Your lens aperture
- Your solar filter ND value

### How Exposures Are Calculated

All exposure times in the generated script are calculated based on:

1. **Base Exposure Tables**: Scientifically measured values for ISO 100, f/8, at 1000m altitude
2. **Sun Altitude Correction**: Atmospheric extinction varies dramatically with sun angle
   - At 60° sun altitude: Minimal atmospheric interference
   - At 0° sun altitude (horizon): Maximum atmospheric extinction (up to 240× longer exposures needed)
3. **Observer Altitude Correction**: Higher elevations have less atmosphere above
   - At sea level (0m): Maximum atmospheric thickness
   - At 3000m: Significantly thinner atmosphere = faster shutters possible
4. **ISO Scaling**: Doubling ISO (e.g., 400→800) halves the exposure time
5. **Aperture Scaling**: Each f-stop change (e.g., f/8→f/5.6) doubles/halves light
6. **ND Filter Scaling**: Solar filter density (ND5.0 = 100,000× reduction)

**Example**: For Baily's Beads at 45° sun altitude, 1000m observer altitude:
- Base (ISO 100, f/8): 1/320s
- With ISO 400, f/5.6: 1/320 × (100/400) × (5.6/8)² = 1/1280s

### Calculated Settings vs. Manual Adjustment

The calculated exposures provide an excellent starting point based on scientific data. However, you may want to fine-tune them based on:
- Specific atmospheric conditions on eclipse day
- Your artistic preferences
- Your camera's dynamic range characteristics

**Recommendation**: Trust the calculated values for your first few shots, then make minor adjustments if needed based on histogram feedback.

## Important Notes

### Solar Filter Safety
- The ND value setting is for documentation purposes in the script
- **Always use proper solar filters** when photographing the sun outside of totality
- **Remove filters only during totality** (for total eclipses only)
- **Never look at or photograph the partial phases without proper filtration**

### Script Timing
- Generated scripts use reference moments (C1, C2, MAX, C3, C4)
- Actual timing should be calculated using Solar Eclipse Workbench with:
  - Precise GPS coordinates
  - Accurate eclipse date and time
  - Local reference moment calculations

### Voice Prompts
If you enable voice prompts, ensure you have the corresponding audio files:
- `voice_prompts_basic.txt` for basic prompts
- `voice_prompts.txt` for extended prompts

These files should be properly configured with your audio file references.

### Camera Synchronization
Camera sync commands are valuable for:
- **Monitoring battery level**: Ensures you don't run out of power during critical moments
- **Checking disk space**: Verifies you have enough storage for all planned shots
- **Timing**: Sync commands are placed during gaps between photography commands (10+ seconds of free time)
- **Adjustments**: You may need to manually adjust sync command timing based on your specific eclipse duration and photography plan

The wizard generates example sync commands, but you should review and adjust their timing to fit your specific schedule and avoid conflicts with important phenomena.

## Configuration Storage

The wizard automatically saves your camera and location configurations for future use. This data is stored in a JSON file located at:
- **Location**: `~/.sew_wizard_config.json` (in your home directory)

### What Gets Saved
- **Cameras**: All saved camera configurations including:
  - Camera name
  - Focal length
  - Aperture range (min/max)
  - Solar filter ND value
- **Locations**: All saved custom observation locations including:
  - Location name
  - Longitude, latitude, altitude
- **Last Used**: Your most recently used camera and location (auto-selected next time)

### Managing Saved Configurations
- **Adding**: Click "Save Camera" or "Save Location" button in the wizard
- **Updating**: Save again with the same name to update the configuration
- **Viewing**: Saved items appear in dropdown menus marked with "(Saved)" for locations
- **Removing**: Edit the `~/.sew_wizard_config.json` file directly to remove unwanted entries

### Manual Configuration Editing
If you need to manually edit or backup your configurations:
```bash
# View your configuration
cat ~/.sew_wizard_config.json

# Backup your configuration
cp ~/.sew_wizard_config.json ~/sew_wizard_config_backup.json

# Edit manually (be careful with JSON syntax)
nano ~/.sew_wizard_config.json
```

**Tip**: Back up your configuration file before major changes or when you have many saved cameras/locations you don't want to lose.

## Troubleshooting

### Wizard Won't Start
- Ensure PyQt6 is properly installed: `pip install pyqt6`
- Check that you have a display server available (X11, Wayland, etc.)
- On headless systems, consider using a virtual display (Xvfb)

### Script Not Generated
- Ensure you filled in all required fields (marked with *)
- Check that you have write permissions to the save location
- Verify the save path is valid

### Generated Script Issues
- Review camera settings for your specific equipment
- Adjust timing offsets based on your eclipse calculations
- Ensure camera name exactly matches your camera model

## Advanced Usage

### Customizing Generated Scripts
After generation, you can edit the script to:
- Add custom commands
- Adjust timing offsets
- Modify camera settings
- Include additional phenomena

### Multiple Camera Setups
To configure multiple cameras:
1. Run the wizard once for each camera
2. Combine scripts manually, or
3. Generate a base script and duplicate commands for each camera

## Support

For issues, questions, or feature requests:
- GitHub: https://github.com/AstroWimSara/SolarEclipseWorkbench
- Documentation: See main README.md

## Version History

- **1.4.0**: Configuration persistence and management
  - Save and load camera configurations
  - Save and load custom observation locations
  - Automatic last-used camera/location selection
  - Configuration file management (~/.sew_wizard_config.json)
  - Removed predefined location list (use saved locations instead)
  - Increased window size for better visibility (900x850)
  - Fixed auto-loading of saved camera/location settings on startup
- **1.3.0**: Initial wizard implementation
  - Modern PyQt6 interface
  - All standard phenomena support
  - Voice prompt integration
  - Dual partial eclipse interval modes (magnitude/time)
