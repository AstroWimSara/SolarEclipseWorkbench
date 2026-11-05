"""Fujifilm X SDK constants from XAPI.H and XAPIOpt.H."""

# --------------------------------------------------------------------------
# Connection interfaces
# --------------------------------------------------------------------------
IF_USB = 0x00000001
IF_WIFI_LOCAL = 0x00000010
IF_WIFI_IP = 0x00000020

# --------------------------------------------------------------------------
# Camera modes
# --------------------------------------------------------------------------
DSC_MODE_TETHER = 0x0001
DSC_MODE_RAW = 0x0002
DSC_MODE_BR = 0x0004
DSC_MODE_WEBCAM = 0x0008

# --------------------------------------------------------------------------
# Priority modes
# --------------------------------------------------------------------------
PRIORITY_CAMERA = 0x0001
PRIORITY_PC = 0x0002

# --------------------------------------------------------------------------
# Release modes (On Mode)
# --------------------------------------------------------------------------
RELEASE_MASK_ONMODE = 0xFF00
RELEASE_MASK_OFFMODE = 0x00FF
RELEASE_SHOOT = 0x0100
RELEASE_S1ON = 0x0200
RELEASE_S2 = 0x0300
RELEASE_BULB_ON = 0x0400
RELEASE_REC_START = 0x0800
RELEASE_BULBS2_ON = 0x0500
RELEASE_PIXELSHIFT = 0x4000
RELEASE_CUSWB = 0x8000
RELEASE_AEON = 0x9000
RELEASE_AFON = 0x9100
RELEASE_AFAEON = 0x9200
RELEASE_AF = 0x9300
RELEASE_INSTANTAF = 0xA000
RELEASE_WBLON = 0x9200

# Release modes (Off Mode)
RELEASE_N_AFOFF = 0x0001
RELEASE_N_AEOFF = 0x0002
RELEASE_N_AFAEOFF = 0x0003
RELEASE_N_S1OFF = 0x0004
RELEASE_N_AF = 0x0020
RELEASE_N_INSTANTAF = 0x0010
RELEASE_N_BULBOFF = 0x0008
RELEASE_REC_STOP = 0x0080
RELEASE_N_BULBS2OFF = 0x0008
RELEASE_N_BULBAFOFF = RELEASE_N_BULBOFF | RELEASE_N_AFOFF
RELEASE_N_BULBAEOFF = RELEASE_N_BULBOFF | RELEASE_N_AEOFF
RELEASE_N_BULBAFAEOFF = RELEASE_N_BULBOFF | RELEASE_N_AFAEOFF
RELEASE_N_BULBS1OFF = RELEASE_N_BULBS2OFF | RELEASE_N_S1OFF
RELEASE_N_BULBAFS1OFF = RELEASE_N_BULBOFF | RELEASE_N_AFOFF | RELEASE_N_S1OFF
RELEASE_N_BULBAES1OFF = RELEASE_N_BULBOFF | RELEASE_N_AEOFF | RELEASE_N_S1OFF
RELEASE_N_BULBAFAES1OFF = RELEASE_N_BULBOFF | RELEASE_N_AFAEOFF | RELEASE_N_S1OFF
RELEASE_CANCEL = 0x000F
RELEASE_N_WBLOFF = 0x0040

# Release modes (On and Off combined)
RELEASE_SHOOT_S1OFF = RELEASE_SHOOT | RELEASE_N_S1OFF
RELEASE_SHOOT_AEOFF = RELEASE_SHOOT | RELEASE_N_AEOFF
RELEASE_SHOOT_AFOFF = RELEASE_SHOOT | RELEASE_N_AFOFF
RELEASE_SHOOT_AFAEOFF = RELEASE_SHOOT | RELEASE_N_AFAEOFF
RELEASE_S2_S1OFF = RELEASE_S2 | RELEASE_N_S1OFF
RELEASE_S2_AFOFF = RELEASE_S2 | RELEASE_N_AFOFF
RELEASE_S2_AEOFF = RELEASE_S2 | RELEASE_N_AEOFF
RELEASE_S2_AFAEOFF = RELEASE_S2 | RELEASE_N_AFAEOFF
RELEASE_S2_AFS1OFF = RELEASE_S2 | RELEASE_N_AFOFF | RELEASE_N_S1OFF
RELEASE_S2_AES1OFF = RELEASE_S2 | RELEASE_N_AEOFF | RELEASE_N_S1OFF
RELEASE_S2_AFAES1OFF = RELEASE_S2 | RELEASE_N_AFOFF | RELEASE_N_AEOFF | RELEASE_N_S1OFF
RELEASE_REC_START_S1OFF = RELEASE_REC_START | RELEASE_N_S1OFF

# --------------------------------------------------------------------------
# Release Mode Ex (On Mode)
# --------------------------------------------------------------------------
RELEASE_EX_S1_ON = 0x00010000
RELEASE_EX_S2_ON = 0x00020000
RELEASE_EX_REC_START = 0x00040000
RELEASE_EX_CUSWB_ON = 0x00080000
RELEASE_EX_INSTANTAF_ON = 0x01000000
RELEASE_EX_AEL_ON = 0x02000000
RELEASE_EX_AFL_ON = 0x04000000
RELEASE_EX_AFON_ON = 0x08000000
RELEASE_EX_WBL_ON = 0x10000000
RELEASE_EX_GRAB = 0x00100000

# Release Mode Ex (Off Mode)
RELEASE_EX_S1_OFF = 0x00000001
RELEASE_EX_S2_OFF = 0x00000002
RELEASE_EX_REC_STOP = 0x00000004
RELEASE_EX_CUSWB_OFF = 0x00000008
RELEASE_EX_CANCEL = 0x00000010
RELEASE_EX_INSTANTAF_OFF = 0x00000100
RELEASE_EX_AEL_OFF = 0x00000200
RELEASE_EX_AFL_OFF = 0x00000400
RELEASE_EX_AFON_OFF = 0x00000800
RELEASE_EX_WBL_OFF = 0x00001000
RELEASE_EX_S2_OFF_S1_OFF = 0x00000003

# Release Mode Ex (On and Off combined)
RELEASE_EX_S1_ON_S2_ON_S2_OFF_S1_OFF = (
    RELEASE_EX_S1_ON | RELEASE_EX_S2_ON | RELEASE_EX_S2_OFF | RELEASE_EX_S1_OFF
)
RELEASE_EX_S2_ON_S2_OFF_S1_OFF = (
    RELEASE_EX_S2_ON | RELEASE_EX_S2_OFF | RELEASE_EX_S1_OFF
)

# --------------------------------------------------------------------------
# Release AF status
# --------------------------------------------------------------------------
RELEASE_OK = 1
RELEASE_AF_FAILURE = 0
RELEASE_AF_UNCHECK = 2
RELEASE_AF_NOMOVE = 4
RELEASE_CWB_AE_OVER = 2
RELEASE_CWB_AE_UNDER = 3

# --------------------------------------------------------------------------
# Release status (bitmap)
# --------------------------------------------------------------------------
RELEASE_STATUS_S1 = 0x0200
RELEASE_STATUS_BULB = 0x0400
RELEASE_STATUS_AF = 0x0800
RELEASE_STATUS_AEL = 0x4000
RELEASE_STATUS_AFL = 0x8000
RELEASE_STATUS_WBL = 0x2000
RELEASE_STATUS_SHOOTING = 0x0100

# --------------------------------------------------------------------------
# Image format
# --------------------------------------------------------------------------
IMAGEFORMAT_RAW = 1
IMAGEFORMAT_LIVE = 4
IMAGEFORMAT_NONE = 5
IMAGEFORMAT_JPEG = 7
IMAGEFORMAT_HEIF = 0x0012
IMAGEFORMAT_JPEG_90 = 0x0607
IMAGEFORMAT_JPEG_180 = 0x0307
IMAGEFORMAT_JPEG_270 = 0x0807
IMAGEFORMAT_RAW_90 = 0x0601
IMAGEFORMAT_RAW_180 = 0x0301
IMAGEFORMAT_RAW_270 = 0x0801
IMAGEFORMAT_LIVE_90 = 0x0604
IMAGEFORMAT_LIVE_180 = 0x0304
IMAGEFORMAT_LIVE_270 = 0x0804
IMAGEFORMAT_HEIF_90 = 0x0612
IMAGEFORMAT_HEIF_180 = 0x0312
IMAGEFORMAT_HEIF_270 = 0x0812

# --------------------------------------------------------------------------
# AE mode
# --------------------------------------------------------------------------
AE_OFF = 0x0001  # Manual
AE_APERTURE_PRIORITY = 0x0003
AE_SHUTTER_PRIORITY = 0x0004
AE_PROGRAM = 0x0006

# --------------------------------------------------------------------------
# Aperture
# --------------------------------------------------------------------------
IRIS_NONE = 0
IRIS_AUTO = 0xFFFF

# --------------------------------------------------------------------------
# Shutter speed (standard)
# --------------------------------------------------------------------------
SHUTTER_UNKNOWN = 0
SHUTTER_1_180000 = 5
SHUTTER_1_160000 = 6
SHUTTER_1_128000 = 7
SHUTTER_1_102400 = 9
SHUTTER_1_80000 = 12
SHUTTER_1_65000 = 15
SHUTTER_1_64000 = 15
SHUTTER_1_60000 = 15
SHUTTER_1_51200 = 19
SHUTTER_1_50000 = 19
SHUTTER_1_40000 = 24
SHUTTER_1_32000 = 30
SHUTTER_1_25600 = 38
SHUTTER_1_25000 = 38
SHUTTER_1_24000 = 43
SHUTTER_1_20000 = 48
SHUTTER_1_16000 = 61
SHUTTER_1_13000 = 76
SHUTTER_1_12800 = 76
SHUTTER_1_12000 = 86
SHUTTER_1_10000 = 96
SHUTTER_1_8000 = 122
SHUTTER_1_6400 = 153
SHUTTER_1_6000 = 172
SHUTTER_1_5000 = 193
SHUTTER_1_4000 = 244
SHUTTER_1_3200 = 307
SHUTTER_1_3000 = 345
SHUTTER_1_2500 = 387
SHUTTER_1_2000 = 488
SHUTTER_1_1600 = 615
SHUTTER_1_1500 = 690
SHUTTER_1_1250 = 775
SHUTTER_1_1000 = 976
SHUTTER_1_800 = 1230
SHUTTER_1_750 = 1381
SHUTTER_1_640 = 1550
SHUTTER_1_500 = 1953
SHUTTER_1_400 = 2460
SHUTTER_1_350 = 2762
SHUTTER_1_320 = 3100
SHUTTER_1_250 = 3906
SHUTTER_1_200 = 4921
SHUTTER_1_180 = 5524
SHUTTER_1_160 = 6200
SHUTTER_1_125 = 7812
SHUTTER_1_100 = 9843
SHUTTER_1_90 = 11048
SHUTTER_1_80 = 12401
SHUTTER_1_60 = 15625
SHUTTER_1_50 = 19686
SHUTTER_1_45 = 22097
SHUTTER_1_40 = 24803
SHUTTER_1_30 = 31250
SHUTTER_1_25 = 39372
SHUTTER_1_20H = 44194
SHUTTER_1_20 = 49606
SHUTTER_1_15 = 62500
SHUTTER_1_13 = 78745
SHUTTER_1_10H = 88388
SHUTTER_1_10 = 99212
SHUTTER_1_8 = 125000
SHUTTER_1_6 = 157490
SHUTTER_1_6H = 176776
SHUTTER_1_5 = 198425
SHUTTER_1_4 = 250000
SHUTTER_1_3 = 314980
SHUTTER_1_3H = 353553
SHUTTER_1_2P5 = 396850
SHUTTER_1_2 = 500000
SHUTTER_1_1P6 = 629960
SHUTTER_1_1P5 = 707106
SHUTTER_1_1P3 = 793700
SHUTTER_1 = 1000000
SHUTTER_1P3 = 1259921
SHUTTER_1P5 = 1414213
SHUTTER_1P5A = 1587401
SHUTTER_1P6 = 1587401
SHUTTER_2 = 2000000
SHUTTER_2P5 = 2519842
SHUTTER_3H = 2828427
SHUTTER_3 = 3174802
SHUTTER_4 = 4000000
SHUTTER_5 = 5039684
SHUTTER_6H = 5656854
SHUTTER_6 = 6349604
SHUTTER_6P5 = 6349604
SHUTTER_8 = 8000000
SHUTTER_10 = 10079368
SHUTTER_10H = 11313708
SHUTTER_13 = 12699208
SHUTTER_15 = 16000000
SHUTTER_20 = 20158736
SHUTTER_20H = 22627416
SHUTTER_25 = 25398416
SHUTTER_30 = 32000000
SHUTTER_35S = 35000000
SHUTTER_40S = 40000000
SHUTTER_40 = 40317473
SHUTTER_45S = 45000000
SHUTTER_50S = 50000000
SHUTTER_50 = 50796833
SHUTTER_55S = 55000000
SHUTTER_60S = 60000000
SHUTTER_60 = 64000000
SHUTTER_80 = 80634947
SHUTTER_100 = 101593667
SHUTTER_2M = 64000030
SHUTTER_125 = 128000000
SHUTTER_160 = 161269894
SHUTTER_200 = 203187334
SHUTTER_4M = 64000060
SHUTTER_250 = 256000000
SHUTTER_320 = 322539788
SHUTTER_400 = 406374669
SHUTTER_8M = 64000090
SHUTTER_500 = 512000000
SHUTTER_640 = 645079577
SHUTTER_800 = 812749338
SHUTTER_15M = 64000120
SHUTTER_1000 = 1024000000
SHUTTER_1300 = 1290159155
SHUTTER_1600 = 1625498677
SHUTTER_30M = 64000150
SHUTTER_2000 = 2048000000
SHUTTER_60M = 64000180
SHUTTER_BULB = -1

# --------------------------------------------------------------------------
# Exposure bias (1/3 EV steps, value = EV * 30)
# --------------------------------------------------------------------------
EXPOSURE_BIAS_P5P00 = 150
EXPOSURE_BIAS_P4P67 = 140
EXPOSURE_BIAS_P4P33 = 130
EXPOSURE_BIAS_P4P00 = 120
EXPOSURE_BIAS_P3P67 = 110
EXPOSURE_BIAS_P3P33 = 100
EXPOSURE_BIAS_P3P00 = 90
EXPOSURE_BIAS_P2P67 = 80
EXPOSURE_BIAS_P2P33 = 70
EXPOSURE_BIAS_P2P00 = 60
EXPOSURE_BIAS_P1P67 = 50
EXPOSURE_BIAS_P1P33 = 40
EXPOSURE_BIAS_P1P00 = 30
EXPOSURE_BIAS_P0P67 = 20
EXPOSURE_BIAS_P0P33 = 10
EXPOSURE_BIAS_0 = 0
EXPOSURE_BIAS_M0P33 = -10
EXPOSURE_BIAS_M0P67 = -20
EXPOSURE_BIAS_M1P00 = -30
EXPOSURE_BIAS_M1P33 = -40
EXPOSURE_BIAS_M1P67 = -50
EXPOSURE_BIAS_M2P00 = -60
EXPOSURE_BIAS_M2P33 = -70
EXPOSURE_BIAS_M2P67 = -80
EXPOSURE_BIAS_M3P00 = -90
EXPOSURE_BIAS_M3P33 = -100
EXPOSURE_BIAS_M3P67 = -110
EXPOSURE_BIAS_M4P00 = -120
EXPOSURE_BIAS_M4P33 = -130
EXPOSURE_BIAS_M4P67 = -140
EXPOSURE_BIAS_M5P00 = -150
AEBIAS_MIN = -150
AEBIAS_MAX = 150

# --------------------------------------------------------------------------
# ISO sensitivity
# --------------------------------------------------------------------------
ISO_40 = 40
ISO_50 = 50
ISO_60 = 60
ISO_64 = 64
ISO_80 = 80
ISO_100 = 100
ISO_125 = 125
ISO_160 = 160
ISO_200 = 200
ISO_250 = 250
ISO_320 = 320
ISO_400 = 400
ISO_500 = 500
ISO_640 = 640
ISO_800 = 800
ISO_1000 = 1000
ISO_1250 = 1250
ISO_1600 = 1600
ISO_2000 = 2000
ISO_2500 = 2500
ISO_3200 = 3200
ISO_4000 = 4000
ISO_5000 = 5000
ISO_6400 = 6400
ISO_8000 = 8000
ISO_10000 = 10000
ISO_12800 = 12800
ISO_16000 = 16000
ISO_20000 = 20000
ISO_25600 = 25600
ISO_32000 = 32000
ISO_40000 = 40000
ISO_51200 = 51200
ISO_64000 = 64000
ISO_80000 = 80000
ISO_102400 = 102400
ISO_AUTO_1 = -1
ISO_AUTO_2 = -2
ISO_AUTO_3 = -3
ISO_AUTO_4 = -4
ISO_AUTO = -10
ISO_AUTO_400 = -400
ISO_AUTO_800 = -800
ISO_AUTO_1600 = -1600
ISO_AUTO_3200 = -3200
ISO_AUTO_6400 = -6400

# --------------------------------------------------------------------------
# Dynamic range
# --------------------------------------------------------------------------
DRANGE_AUTO = 0xFFFF
DRANGE_100 = 100
DRANGE_200 = 200
DRANGE_400 = 400
DRANGE_800 = 800

# --------------------------------------------------------------------------
# Metering mode
# --------------------------------------------------------------------------
METERING_AVERAGE = 0x0001
METERING_CENTER_WEIGHTED = 0x0002
METERING_MULTI = 0x0003
METERING_CENTER = 0x0004

# --------------------------------------------------------------------------
# Force mode
# --------------------------------------------------------------------------
FORCESHOOTSTANDBY_SHOOT = 0x0001
FORCESHOOTSTANDBY_PLAYBACK = 0x0002

# --------------------------------------------------------------------------
# Drive mode
# --------------------------------------------------------------------------
DRIVE_MODE_INVALID = 0xFFFF
DRIVE_MODE_CH = 0x0002
DRIVE_MODE_CL = 0x0003
DRIVE_MODE_S = 0x0004
DRIVE_MODE_MULTI_EXPOSURE = 0x0005
DRIVE_MODE_ADVFILTER = 0x0006
DRIVE_MODE_PANORAMA = 0x0007
DRIVE_MODE_MOVIE = 0x0008
DRIVE_MODE_HDR = 0x0009
DRIVE_MODE_BKT_AE = 0x000A
DRIVE_MODE_BKT_ISO = 0x000B
DRIVE_MODE_BKT_FILMSIMULATION = 0x000C
DRIVE_MODE_BKT_WHITEBALANCE = 0x000D
DRIVE_MODE_BKT_DYNAMICRANGE = 0x000E
DRIVE_MODE_BKT_FOCUS = 0x000F
DRIVE_MODE_PIXELSHIFTMULTISHOT = 0x0010
DRIVE_MODE_CH_CROP = 0x0011
DRIVE_MODE_PIXELSHIFTMULTISHOT_FEWERFRAMES = 0x0012

# --------------------------------------------------------------------------
# Mode (custom presets)
# --------------------------------------------------------------------------
MODE_STILL_C0 = 0x0001
MODE_STILL_C1 = 0x0002
MODE_STILL_C2 = 0x0003
MODE_STILL_C3 = 0x0004
MODE_STILL_C4 = 0x0005
MODE_STILL_C5 = 0x0006
MODE_STILL_C6 = 0x0007
MODE_STILL_C7 = 0x0008
MODE_STILL_ADVFILTER = 0x0081
MODE_STILL_SP = 0x00B1
MODE_STILL_AUTO = 0x00F0
MODE_MOVIE_C0 = 0x0101
MODE_MOVIE_C1 = 0x0102
MODE_MOVIE_C2 = 0x0103
MODE_MOVIE_C3 = 0x0104
MODE_MOVIE_C4 = 0x0105
MODE_MOVIE_C5 = 0x0106
MODE_MOVIE_C6 = 0x0107
MODE_MOVIE_C7 = 0x0108
MODE_MOVIE_VLOG = 0x0161

# --------------------------------------------------------------------------
# White balance
# --------------------------------------------------------------------------
WB_AUTO = 0x0002
WB_AUTO_WHITE_PRIORITY = 0x8020
WB_AUTO_AMBIENCE_PRIORITY = 0x8021
WB_DAYLIGHT = 0x0004
WB_INCANDESCENT = 0x0006
WB_UNDER_WATER = 0x0008
WB_FLUORESCENT1 = 0x8001
WB_FLUORESCENT2 = 0x8002
WB_FLUORESCENT3 = 0x8003
WB_SHADE = 0x8006
WB_COLORTEMP = 0x8007
WB_CUSTOM1 = 0x8008
WB_CUSTOM2 = 0x8009
WB_CUSTOM3 = 0x800A
WB_CUSTOM4 = 0x800B
WB_CUSTOM5 = 0x800C

# --------------------------------------------------------------------------
# White balance color temperature
# --------------------------------------------------------------------------
WB_COLORTEMP_2500 = 2500
WB_COLORTEMP_2550 = 2550
WB_COLORTEMP_2650 = 2650
WB_COLORTEMP_2700 = 2700
WB_COLORTEMP_2800 = 2800
WB_COLORTEMP_2850 = 2850
WB_COLORTEMP_2950 = 2950
WB_COLORTEMP_3000 = 3000
WB_COLORTEMP_3100 = 3100
WB_COLORTEMP_3200 = 3200
WB_COLORTEMP_3300 = 3300
WB_COLORTEMP_3400 = 3400
WB_COLORTEMP_3600 = 3600
WB_COLORTEMP_3700 = 3700
WB_COLORTEMP_3800 = 3800
WB_COLORTEMP_4000 = 4000
WB_COLORTEMP_4200 = 4200
WB_COLORTEMP_4300 = 4300
WB_COLORTEMP_4500 = 4500
WB_COLORTEMP_4800 = 4800
WB_COLORTEMP_5000 = 5000
WB_COLORTEMP_5300 = 5300
WB_COLORTEMP_5600 = 5600
WB_COLORTEMP_5900 = 5900
WB_COLORTEMP_6300 = 6300
WB_COLORTEMP_6700 = 6700
WB_COLORTEMP_7100 = 7100
WB_COLORTEMP_7700 = 7700
WB_COLORTEMP_8300 = 8300
WB_COLORTEMP_9100 = 9100
WB_COLORTEMP_10000 = 10000
WB_COLORTEMP_CURRENT = 0

# --------------------------------------------------------------------------
# Media record
# --------------------------------------------------------------------------
MEDIAREC_RAWJPEG = 0x0001
MEDIAREC_RAW = 0x0002
MEDIAREC_JPEG = 0x0003
MEDIAREC_OFF = 0x0004
MEDIAREC_RAWJPEGHEIF = MEDIAREC_RAWJPEG
MEDIAREC_JPEGHEIF = MEDIAREC_JPEG

# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
YES = 0x0001
NO = 0x0000
ON = 0x0001
OFF = 0x0002

# --------------------------------------------------------------------------
# Error details
# --------------------------------------------------------------------------
ERROR_DETAIL_S1 = 0x00000001
ERROR_DETAIL_AEL = 0x00000002
ERROR_DETAIL_AFL = 0x00000004
ERROR_DETAIL_INSTANTAF = 0x00000008
ERROR_DETAIL_AFON = 0x00000010
ERROR_DETAIL_SHOOTING = 0x00000020
ERROR_DETAIL_SHOOTINGCOUNTDOWN = 0x00000040
ERROR_DETAIL_RECORDING = 0x00000080
ERROR_DETAIL_LIVEVIEW = 0x00000100
ERROR_DETAIL_UNTRANSFERRED_IMAGE = 0x00000200

# --------------------------------------------------------------------------
# Error codes
# --------------------------------------------------------------------------
ERRCODE_NOERR = 0x00000000
ERRCODE_SEQUENCE = 0x00001001
ERRCODE_PARAM = 0x00001002
ERRCODE_INVALID_CAMERA = 0x00001003
ERRCODE_LOADLIB = 0x00001004
ERRCODE_UNSUPPORTED = 0x00001005
ERRCODE_BUSY = 0x00001006
ERRCODE_AF_TIMEOUT = 0x00001007
ERRCODE_SHOOT_ERROR = 0x00001008
ERRCODE_FRAME_FULL = 0x00001009
ERRCODE_STANDBY = 0x00001010
ERRCODE_NODRIVER = 0x00001011
ERRCODE_NO_MODEL_MODULE = 0x00001012
ERRCODE_API_NOTFOUND = 0x00001013
ERRCODE_API_MISMATCH = 0x00001014
ERRCODE_INVALID_USBMODE = 0x00001015
ERRCODE_FORCEMODE_BUSY = 0x00001016
ERRCODE_RUNNING_OTHER_FUNCTION = 0x00001017
ERRCODE_COMMUNICATION = 0x00002001
ERRCODE_TIMEOUT = 0x00002002
ERRCODE_COMBINATION = 0x00002003
ERRCODE_WRITEERROR = 0x00002004
ERRCODE_CARDFULL = 0x00002005
ERRCODE_HARDWARE = 0x00003001
ERRCODE_INTERNAL = 0x00009001
ERRCODE_MEMFULL = 0x00009002
ERRCODE_UNKNOWN = 0x00009100

# Return values
COMPLETE = 0
ERROR = -1

# --------------------------------------------------------------------------
# API codes (from XAPI.H enum)
# --------------------------------------------------------------------------
API_CODE_Init = 0x1001
API_CODE_Exit = 0x1002
API_CODE_Detect = 0x1010
API_CODE_Append = 0x1012
API_CODE_Close = 0x1022
API_CODE_PowerOFF = 0x1023
API_CODE_OpenEx = 0x1024
API_CODE_GetErrorNumber = 0x1031
API_CODE_GetVersionString = 0x1032
API_CODE_GetErrorDetails = 0x1033
API_CODE_GetDeviceInfo = 0x1041
API_CODE_WriteDeviceName = 0x1042
API_CODE_GetFirmwareVersion = 0x1043
API_CODE_GetLensInfo = 0x1044
API_CODE_GetLensVersion = 0x1045
API_CODE_GetDeviceInfoEx = 0x1047
API_CODE_CapPriorityMode = 0x1101
API_CODE_SetPriorityMode = 0x1102
API_CODE_GetPriorityMode = 0x1103
API_CODE_CapRelease = 0x1111
API_CODE_Release = 0x1112
API_CODE_GetReleaseStatus = 0x1113
API_CODE_CapReleaseEx = 0x1115
API_CODE_ReleaseEx = 0x1116
API_CODE_CapReleaseStatus = 0x1118
API_CODE_GetBufferCapacity = 0x1200
API_CODE_ReadImageInfo = 0x1201
API_CODE_ReadPreview = 0x1202
API_CODE_ReadImage = 0x1203
API_CODE_DeleteImage = 0x1204
API_CODE_CapAEMode = 0x1301
API_CODE_SetAEMode = 0x1302
API_CODE_GetAEMode = 0x1303
API_CODE_CapShutterSpeed = 0x1304
API_CODE_SetShutterSpeed = 0x1305
API_CODE_GetShutterSpeed = 0x1306
API_CODE_CapExposureBias = 0x1307
API_CODE_SetExposureBias = 0x1308
API_CODE_GetExposureBias = 0x1309
API_CODE_CapSensitivity = 0x1311
API_CODE_SetSensitivity = 0x1312
API_CODE_GetSensitivity = 0x1313
API_CODE_CapDynamicRange = 0x1314
API_CODE_SetDynamicRange = 0x1315
API_CODE_GetDynamicRange = 0x1316
API_CODE_CapMeteringMode = 0x1317
API_CODE_SetMeteringMode = 0x1318
API_CODE_GetMeteringMode = 0x1319
API_CODE_CapLensZoomPos = 0x1321
API_CODE_SetLensZoomPos = 0x1322
API_CODE_GetLensZoomPos = 0x1323
API_CODE_CapAperture = 0x1324
API_CODE_SetAperture = 0x1325
API_CODE_GetAperture = 0x1326
API_CODE_CapWBMode = 0x1331
API_CODE_SetWBMode = 0x1332
API_CODE_GetWBMode = 0x1333
API_CODE_CapWBColorTemp = 0x1334
API_CODE_SetWBColorTemp = 0x1335
API_CODE_GetWBColorTemp = 0x1336
API_CODE_CapMediaRecord = 0x1351
API_CODE_SetMediaRecord = 0x1352
API_CODE_GetMediaRecord = 0x1353
API_CODE_CapForceMode = 0x1371
API_CODE_SetForceMode = 0x1372
API_CODE_SetBackupSettings = 0x1375
API_CODE_GetBackupSettings = 0x1376
API_CODE_SetDriveMode = 0x1377
API_CODE_GetDriveMode = 0x1378
API_CODE_CapDriveMode = 0x1379
API_CODE_CapMode = 0x137A
API_CODE_SetMode = 0x137B
API_CODE_GetMode = 0x137C
API_CODE_CapProp = 0x1401
API_CODE_SetProp = 0x1402
API_CODE_GetProp = 0x1403

# --------------------------------------------------------------------------
# Extended API codes (from XAPIOpt.H)
# --------------------------------------------------------------------------
# Exposure
API_CODE_CapHighFrequencyFlickerlessMode = 0x2063
API_CODE_SetHighFrequencyFlickerlessMode = 0x2064
API_CODE_GetHighFrequencyFlickerlessMode = 0x2065

# Shooting condition setting
API_CODE_SetImageSize = 0x2101
API_CODE_GetImageSize = 0x2102
API_CODE_SetSharpness = 0x2103
API_CODE_GetSharpness = 0x2104
API_CODE_SetColorMode = 0x2105
API_CODE_GetColorMode = 0x2106
API_CODE_SetFilmSimulationMode = 0x2121
API_CODE_GetFilmSimulationMode = 0x2122
API_CODE_SetColorSpace = 0x2127
API_CODE_GetColorSpace = 0x2128
API_CODE_SetImageQuality = 0x2129
API_CODE_GetImageQuality = 0x2130
API_CODE_SetNoiseReduction = 0x2131
API_CODE_GetNoiseReduction = 0x2132
API_CODE_SetFaceDetectionMode = 0x2135
API_CODE_GetFaceDetectionMode = 0x2136
API_CODE_SetMacroMode = 0x2139
API_CODE_GetMacroMode = 0x2140
API_CODE_SetHighLightTone = 0x2141
API_CODE_GetHighLightTone = 0x2142
API_CODE_SetShadowTone = 0x2143
API_CODE_GetShadowTone = 0x2144
API_CODE_SetLongExposureNR = 0x2145
API_CODE_GetLongExposureNR = 0x2146
API_CODE_SetFullTimeManualFocus = 0x2148
API_CODE_GetFullTimeManualFocus = 0x2149
API_CODE_SetRAWCompression = 0x2150
API_CODE_GetRAWCompression = 0x2151
API_CODE_SetGrainEffect = 0x2152
API_CODE_GetGrainEffect = 0x2153
API_CODE_SetShadowing = 0x2154
API_CODE_GetShadowing = 0x2155
API_CODE_SetWideDynamicRange = 0x2156
API_CODE_GetWideDynamicRange = 0x2157
API_CODE_SetBlackImageTone = 0x2158
API_CODE_GetBlackImageTone = 0x2159
API_CODE_SetRAWOutputDepth = 0x2160
API_CODE_GetRAWOutputDepth = 0x2161
API_CODE_SetSmoothSkinEffect = 0x2162
API_CODE_GetSmoothSkinEffect = 0x2163
API_CODE_GetDetectedFaceFrame = 0x2166
API_CODE_SetDetectedFaceFrame = 0x2167
API_CODE_SetColorChromeBlue = 0x2168
API_CODE_GetColorChromeBlue = 0x2169
API_CODE_SetMonochromaticColor = 0x216A
API_CODE_GetMonochromaticColor = 0x216B
API_CODE_SetClarityMode = 0x216C
API_CODE_GetClarityMode = 0x216D
API_CODE_GetCommandDialStatus = 0x216E
API_CODE_CapImageSize = 0x2180
API_CODE_CapSharpness = 0x2181
API_CODE_CapColorMode = 0x2182
API_CODE_CapFilmSimulationMode = 0x2183
API_CODE_CapColorSpace = 0x2184
API_CODE_CapImageQuality = 0x2185
API_CODE_CapNoiseReduction = 0x2186
API_CODE_CapFaceDetectionMode = 0x2187
API_CODE_CapHighLightTone = 0x2188
API_CODE_CapShadowTone = 0x2189
API_CODE_CapLongExposureNR = 0x218A
API_CODE_CapCustomSettingAutoUpdate = 0x218B
API_CODE_SetCustomSettingAutoUpdate = 0x218C
API_CODE_GetCustomSettingAutoUpdate = 0x218D
API_CODE_CapFullTimeManualFocus = 0x218E
API_CODE_CapRAWCompression = 0x218F
API_CODE_CapGrainEffect = 0x2190
API_CODE_CapShadowing = 0x2191
API_CODE_CapWideDynamicRange = 0x2192
API_CODE_CapRAWOutputDepth = 0x2193
API_CODE_CapSmoothSkinEffect = 0x2194
API_CODE_CapColorChromeBlue = 0x2195
API_CODE_CapMonochromaticColor = 0x2196
API_CODE_CapClarityMode = 0x2197
API_CODE_CapImageFormat = 0x219D
API_CODE_SetImageFormat = 0x219E
API_CODE_GetImageFormat = 0x219F
API_CODE_CapPortraitEnhancer = 0x21A0
API_CODE_SetPortraitEnhancer = 0x21A1
API_CODE_GetPortraitEnhancer = 0x21A2

# Lens & Focus control
API_CODE_SetFocusMode = 0x2201
API_CODE_GetFocusMode = 0x2202
API_CODE_SetAFMode = 0x2203
API_CODE_GetAFMode = 0x2204
API_CODE_SetFocusArea = 0x2205
API_CODE_GetFocusArea = 0x2206
API_CODE_SetFocusPos = 0x2207
API_CODE_GetFocusPos = 0x2208
API_CODE_CapFocusMode = 0x2209
API_CODE_GetAFStatus = 0x220A
API_CODE_SetShutterPriorityMode = 0x2217
API_CODE_GetShutterPriorityMode = 0x2218
API_CODE_SetInstantAFMode = 0x2219
API_CODE_GetInstantAFMode = 0x2220
API_CODE_SetPreAFMode = 0x2221
API_CODE_GetPreAFMode = 0x2222
API_CODE_SetAFIlluminator = 0x2223
API_CODE_GetAFIlluminator = 0x2224
API_CODE_SetLensISSwitch = 0x2225
API_CODE_GetLensISSwitch = 0x2226
API_CODE_SetISMode = 0x2227
API_CODE_GetISMode = 0x2228
API_CODE_SetLMOMode = 0x2229
API_CODE_GetLMOMode = 0x2230
API_CODE_GetTNumber = 0x2233
API_CODE_CapAFMode = 0x2234
API_CODE_CapFocusArea = 0x2235
API_CODE_CapAFStatus = 0x2236
API_CODE_CapShutterPriorityMode = 0x2237
API_CODE_CapInstantAFMode = 0x2238
API_CODE_CapPreAFMode = 0x2239
API_CODE_CapAFIlluminator = 0x223A
API_CODE_CapISMode = 0x223B
API_CODE_CapLMOMode = 0x223C
API_CODE_CapEyeAFMode = 0x223D
API_CODE_CapFocusPoints = 0x223E
API_CODE_CapMFAssistMode = 0x223F
API_CODE_CapFocusCheckMode = 0x2240
API_CODE_CapInterlockAEAFArea = 0x2241
API_CODE_CapCropMode = 0x2242
API_CODE_CapFocusLimiterPos = 0x2243
API_CODE_CapFocusLimiterMode = 0x2244
API_CODE_CapSubjectDetectionMode = 0x2245
API_CODE_SetSubjectDetectionMode = 0x2246
API_CODE_GetSubjectDetectionMode = 0x2247
API_CODE_SetEyeAFMode = 0x2255
API_CODE_GetEyeAFMode = 0x2256
API_CODE_SetFocusPoints = 0x2257
API_CODE_GetFocusPoints = 0x2258
API_CODE_CapFocusPos = 0x2259
API_CODE_CapLensISSwitch = 0x2260
API_CODE_SetMFAssistMode = 0x2261
API_CODE_GetMFAssistMode = 0x2262
API_CODE_SetFocusCheckMode = 0x2263
API_CODE_GetFocusCheckMode = 0x2264
API_CODE_SetInterlockAEAFArea = 0x2265
API_CODE_GetInterlockAEAFArea = 0x2266
API_CODE_SetCropMode = 0x2267
API_CODE_GetCropMode = 0x2268
API_CODE_GetCropAreaFrameInfo = 0x2269
API_CODE_SetFocusLimiterPos = 0x226A
API_CODE_GetFocusLimiterIndicator = 0x226B
API_CODE_GetFocusLimiterRange = 0x226C
API_CODE_SetFocusLimiterMode = 0x226D
API_CODE_GetFocusLimiterMode = 0x226E
API_CODE_CapCropZoom = 0x226F
API_CODE_SetCropZoom = 0x2270
API_CODE_GetCropZoom = 0x2271
API_CODE_CapZoomOperation = 0x2272
API_CODE_SetZoomOperation = 0x2273
API_CODE_CapFocusOperation = 0x2274
API_CODE_SetFocusOperation = 0x2275
API_CODE_CapZoomSpeed = 0x2279
API_CODE_SetZoomSpeed = 0x227A
API_CODE_GetZoomSpeed = 0x227B
API_CODE_CapFocusSpeed = 0x227C
API_CODE_SetFocusSpeed = 0x227D
API_CODE_GetFocusSpeed = 0x227E
API_CODE_GetTiltShiftLensStatus = 0x227F
API_CODE_CapAFZoneCustom = 0x2287
API_CODE_SetAFZoneCustom = 0x2288
API_CODE_GetAFZoneCustom = 0x2289

# White balance control
API_CODE_SetWhiteBalanceMode = 0x2301
API_CODE_GetWhiteBalanceMode = 0x2302
API_CODE_SetWhiteBalanceTune = 0x2304
API_CODE_GetWhiteBalanceTune = 0x2305
API_CODE_CapWhiteBalanceTune = 0x2324
API_CODE_SetCustomWBArea = 0x2353
API_CODE_GetCustomWBArea = 0x2354

# Shoot
API_CODE_SetCaptureDelay = 0x3021
API_CODE_GetCaptureDelay = 0x3022
API_CODE_CapCaptureDelay = 0x3025

# Live view control
API_CODE_StartLiveView = 0x3301
API_CODE_StopLiveView = 0x3302
API_CODE_SetLiveViewImageQuality = 0x3323
API_CODE_GetLiveViewImageQuality = 0x3324
API_CODE_SetLiveViewImageSize = 0x3325
API_CODE_GetLiveViewImageSize = 0x3326
API_CODE_SetThroughImageZoom = 0x3327
API_CODE_GetThroughImageZoom = 0x3328
API_CODE_CapLiveViewImageQuality = 0x3329
API_CODE_CapLiveViewImageSize = 0x332A
API_CODE_CapThroughImageZoom = 0x332B
API_CODE_CapLiveViewStatus = 0x332C
API_CODE_GetLiveViewStatus = 0x332D
API_CODE_CapLiveViewMode = 0x332E
API_CODE_SetLiveViewMode = 0x332F
API_CODE_GetLiveViewMode = 0x3330
API_CODE_CapLiveViewImageRatio = 0x3331
API_CODE_SetLiveViewImageRatio = 0x3332
API_CODE_GetLiveViewImageRatio = 0x3333

# Utility
API_CODE_SetDateTime = 0x4001
API_CODE_GetDateTime = 0x4002
API_CODE_SetDateTimeDispFormat = 0x4003
API_CODE_GetDateTimeDispFormat = 0x4004
API_CODE_SetWorldClock = 0x4005
API_CODE_GetWorldClock = 0x4006
API_CODE_SetTimeDifference = 0x4007
API_CODE_GetTimeDifference = 0x4008
API_CODE_ResetSetting = 0x4020
API_CODE_SetSilentMode = 0x4021
API_CODE_GetSilentMode = 0x4022
API_CODE_SetBeep = 0x4025
API_CODE_GetBeep = 0x4026
API_CODE_SetFunctionLock = 0x4039
API_CODE_GetFunctionLock = 0x4040
API_CODE_SetComment = 0x4043
API_CODE_GetComment = 0x4044
API_CODE_SetCopyright = 0x4045
API_CODE_GetCopyright = 0x4046
API_CODE_SetFilenamePrefix = 0x4047
API_CODE_GetFilenamePrefix = 0x4048
API_CODE_CheckBatteryInfo = 0x4055
API_CODE_GetShutterCount = 0x4101
API_CODE_GetShutterCountEx = 0x4113
API_CODE_GetMediaStatus = 0x4070
API_CODE_GetMediaCapacity = 0x4068

# --------------------------------------------------------------------------
# Shutter speed name lookup (value -> human-readable string)
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Focus modes
# --------------------------------------------------------------------------
SDK_FOCUS_MANUAL = 0x0001
SDK_FOCUS_AFS = 0x8001
SDK_FOCUS_AFC = 0x8002

# --------------------------------------------------------------------------
# Image quality (for SetImageQuality/GetImageQuality)
# --------------------------------------------------------------------------
IMAGE_QUALITY_RAW = 0x0001
IMAGE_QUALITY_FINE = 0x0002
IMAGE_QUALITY_NORMAL = 0x0003
IMAGE_QUALITY_FINE_PLUS_RAW = 0x0004
IMAGE_QUALITY_NORMAL_PLUS_RAW = 0x0005

# --------------------------------------------------------------------------
# Live view sizes
# --------------------------------------------------------------------------
# The SDK calls these L, M and S, and its own sample gives the widths: the
# names here said XGA/VGA/QVGA with resolutions to match, which are not the
# sizes the body produces.  The numbers were right, so this is what was on
# screen all along - it was only ever described wrongly.
LIVEVIEW_SIZE_L = 0x0001     # L, 1280 wide
LIVEVIEW_SIZE_M = 0x0002     # M, 800 wide
LIVEVIEW_SIZE_S = 0x0003     # S, 640 wide

#: Kept so existing callers and saved settings keep working.
LIVEVIEW_SIZE_XGA = LIVEVIEW_SIZE_L
LIVEVIEW_SIZE_VGA = LIVEVIEW_SIZE_M
LIVEVIEW_SIZE_QVGA = LIVEVIEW_SIZE_S

# --------------------------------------------------------------------------
# Live view quality
# --------------------------------------------------------------------------
LIVEVIEW_QUALITY_FINE = 0x0001
LIVEVIEW_QUALITY_NORMAL = 0x0002
LIVEVIEW_QUALITY_BASIC = 0x0003

# --------------------------------------------------------------------------
# MF Assist modes
# --------------------------------------------------------------------------
MF_ASSIST_STANDARD = 0x0001
MF_ASSIST_DIGITAL_SPLIT = 0x0002

# --------------------------------------------------------------------------
# Focus mode name lookup
# --------------------------------------------------------------------------
FOCUS_MODE_NAMES: dict[int, str] = {
    SDK_FOCUS_MANUAL: "MF",
    SDK_FOCUS_AFS: "AF-S",
    SDK_FOCUS_AFC: "AF-C",
}

# --------------------------------------------------------------------------
# AE mode name lookup
# --------------------------------------------------------------------------
AE_MODE_NAMES: dict[int, str] = {
    AE_OFF: "Manual",
    AE_APERTURE_PRIORITY: "Aperture Priority",
    AE_SHUTTER_PRIORITY: "Shutter Priority",
    AE_PROGRAM: "Program",
}

# --------------------------------------------------------------------------
# Drive mode name lookup
# --------------------------------------------------------------------------
DRIVE_MODE_NAMES: dict[int, str] = {
    DRIVE_MODE_S: "Single",
    DRIVE_MODE_CL: "CL",
    DRIVE_MODE_CH: "CH",
    DRIVE_MODE_MULTI_EXPOSURE: "Multi Exposure",
    DRIVE_MODE_ADVFILTER: "Advanced Filter",
    DRIVE_MODE_PANORAMA: "Panorama",
    DRIVE_MODE_MOVIE: "Movie",
    DRIVE_MODE_HDR: "HDR",
    DRIVE_MODE_BKT_AE: "AE Bracket",
    DRIVE_MODE_BKT_ISO: "ISO Bracket",
    DRIVE_MODE_BKT_FILMSIMULATION: "Film Simulation Bracket",
    DRIVE_MODE_BKT_WHITEBALANCE: "WB Bracket",
    DRIVE_MODE_BKT_DYNAMICRANGE: "DR Bracket",
    DRIVE_MODE_BKT_FOCUS: "Focus Bracket",
    DRIVE_MODE_PIXELSHIFTMULTISHOT: "Pixel Shift",
    DRIVE_MODE_CH_CROP: "CH Crop",
    DRIVE_MODE_PIXELSHIFTMULTISHOT_FEWERFRAMES: "Pixel Shift (Fewer)",
    # Model-specific values reported by all current cameras via CapDriveMode.
    # These differ from the generic XAPI.H defines above.
    0x1000: "CL",
    0x10F0: "CH",
    0x4000: "Bracket",
}

# --------------------------------------------------------------------------
# WB mode name lookup
# --------------------------------------------------------------------------
WB_MODE_NAMES: dict[int, str] = {
    WB_AUTO: "Auto",
    WB_AUTO_WHITE_PRIORITY: "Auto (White Priority)",
    WB_AUTO_AMBIENCE_PRIORITY: "Auto (Ambience Priority)",
    WB_DAYLIGHT: "Daylight",
    WB_INCANDESCENT: "Incandescent",
    WB_SHADE: "Shade",
    WB_FLUORESCENT1: "Fluorescent 1",
    WB_FLUORESCENT2: "Fluorescent 2",
    WB_FLUORESCENT3: "Fluorescent 3",
    WB_COLORTEMP: "Color Temp",
    WB_CUSTOM1: "Custom 1",
    WB_CUSTOM2: "Custom 2",
    WB_CUSTOM3: "Custom 3",
}

# --------------------------------------------------------------------------
# Image quality name lookup
# --------------------------------------------------------------------------
IMAGE_QUALITY_NAMES: dict[int, str] = {
    IMAGE_QUALITY_RAW: "RAW",
    IMAGE_QUALITY_FINE: "FINE",
    IMAGE_QUALITY_NORMAL: "NORMAL",
    IMAGE_QUALITY_FINE_PLUS_RAW: "FINE+RAW",
    IMAGE_QUALITY_NORMAL_PLUS_RAW: "NORMAL+RAW",
}

# --------------------------------------------------------------------------
# Shutter speed name lookup (value -> human-readable string)
# --------------------------------------------------------------------------
MF_ASSIST_MODE_NAMES: dict[int, str] = {
    MF_ASSIST_STANDARD: "Standard",
    MF_ASSIST_DIGITAL_SPLIT: "Digital Split Image",
}

LIVEVIEW_SIZE_NAMES: dict[int, str] = {
    LIVEVIEW_SIZE_XGA: "XGA (1024x768)",
    LIVEVIEW_SIZE_VGA: "VGA (640x480)",
    LIVEVIEW_SIZE_QVGA: "QVGA (320x240)",
}

LIVEVIEW_QUALITY_NAMES: dict[int, str] = {
    LIVEVIEW_QUALITY_FINE: "Fine",
    LIVEVIEW_QUALITY_NORMAL: "Normal",
}

SHUTTER_SPEED_NAMES: dict[int, str] = {
    SHUTTER_UNKNOWN: "Unknown",
    SHUTTER_1_180000: '1/180000"',
    SHUTTER_1_160000: '1/160000"',
    SHUTTER_1_128000: '1/128000"',
    SHUTTER_1_102400: '1/102400"',
    SHUTTER_1_80000: '1/80000"',
    SHUTTER_1_64000: '1/64000"',
    SHUTTER_1_51200: '1/51200"',
    SHUTTER_1_40000: '1/40000"',
    SHUTTER_1_32000: '1/32000"',
    SHUTTER_1_25600: '1/25600"',
    SHUTTER_1_24000: '1/24000"',
    SHUTTER_1_20000: '1/20000"',
    SHUTTER_1_16000: '1/16000"',
    SHUTTER_1_12800: '1/12800"',
    SHUTTER_1_12000: '1/12000"',
    SHUTTER_1_10000: '1/10000"',
    SHUTTER_1_8000: '1/8000"',
    SHUTTER_1_6400: '1/6400"',
    SHUTTER_1_6000: '1/6000"',
    SHUTTER_1_5000: '1/5000"',
    SHUTTER_1_4000: '1/4000"',
    SHUTTER_1_3200: '1/3200"',
    SHUTTER_1_3000: '1/3000"',
    SHUTTER_1_2500: '1/2500"',
    SHUTTER_1_2000: '1/2000"',
    SHUTTER_1_1600: '1/1600"',
    SHUTTER_1_1500: '1/1500"',
    SHUTTER_1_1250: '1/1250"',
    SHUTTER_1_1000: '1/1000"',
    SHUTTER_1_800: '1/800"',
    SHUTTER_1_750: '1/750"',
    SHUTTER_1_640: '1/640"',
    SHUTTER_1_500: '1/500"',
    SHUTTER_1_400: '1/400"',
    SHUTTER_1_350: '1/350"',
    SHUTTER_1_320: '1/320"',
    SHUTTER_1_250: '1/250"',
    SHUTTER_1_200: '1/200"',
    SHUTTER_1_180: '1/180"',
    SHUTTER_1_160: '1/160"',
    SHUTTER_1_125: '1/125"',
    SHUTTER_1_100: '1/100"',
    SHUTTER_1_90: '1/90"',
    SHUTTER_1_80: '1/80"',
    SHUTTER_1_60: '1/60"',
    SHUTTER_1_50: '1/50"',
    SHUTTER_1_45: '1/45"',
    SHUTTER_1_40: '1/40"',
    SHUTTER_1_30: '1/30"',
    SHUTTER_1_25: '1/25"',
    SHUTTER_1_20: '1/20"',
    SHUTTER_1_15: '1/15"',
    SHUTTER_1_13: '1/13"',
    SHUTTER_1_10: '1/10"',
    SHUTTER_1_8: '1/8"',
    SHUTTER_1_6: '1/6"',
    SHUTTER_1_5: '1/5"',
    SHUTTER_1_4: '1/4"',
    SHUTTER_1_3: '1/3"',
    SHUTTER_1_2P5: '1/2.5"',
    SHUTTER_1_2: '1/2"',
    SHUTTER_1_1P6: '1/1.6"',
    SHUTTER_1_1P5: '1/1.5"',
    SHUTTER_1_1P3: '1/1.3"',
    SHUTTER_1: '1"',
    SHUTTER_1P3: '1.3"',
    SHUTTER_1P6: '1.6"',
    SHUTTER_2: '2"',
    SHUTTER_2P5: '2.5"',
    SHUTTER_3: '3"',
    SHUTTER_4: '4"',
    SHUTTER_5: '5"',
    SHUTTER_6: '6"',
    SHUTTER_8: '8"',
    SHUTTER_10: '10"',
    SHUTTER_13: '13"',
    SHUTTER_15: '15"',
    SHUTTER_20: '20"',
    SHUTTER_25: '25"',
    SHUTTER_30: '30"',
    SHUTTER_40: '40"',
    SHUTTER_50: '52"',
    SHUTTER_60: '60"',
    SHUTTER_2M: '2min',
    SHUTTER_4M: '4min',
    SHUTTER_8M: '8min',
    SHUTTER_15M: '15min',
    SHUTTER_30M: '30min',
    SHUTTER_60M: '60min',
    SHUTTER_BULB: 'BULB',
}

# --------------------------------------------------------------------------
# API parameter numbers
# --------------------------------------------------------------------------
# XSDK_SetProp and XSDK_GetProp take an api_param alongside the api_code, and
# it is not free-form: each API has one value the body expects, listed per
# model in the SDK's own headers as <MODEL>_API_PARAM_<Api>.  Passing 0 for
# everything - which this wrapper did - is answered 0x1002 "Invalid parameter"
# by every API whose number is not 0, which is most of them.  That is what made
# the focus mode and the live view size unreadable and unsettable.
#
# Confirmed against the vendor's own LiveView sample, which passes 1 for the
# size and quality and 0 for the start:
#     set_prop_l(handle, API_CODE_SetLiveViewImageSize, 1, SDK_LIVEVIEW_SIZE_L)
#     set_prop(handle, API_CODE_StartLiveView, 0)
#
# Generated from HEADERS/X-T4.h.  The numbers are mostly a property of the API
# rather than the body - eighteen model headers agree on the live view and
# focus ones - but not always: CheckBatteryInfo is 6 here and 8 on eleven other
# models, so this table is the X-T4's and a different body needs its own.
API_PARAM: dict[int, int] = {
    API_CODE_CapFocusMode: 2,
    API_CODE_CapFocusPos: 2,
    API_CODE_CapLensISSwitch: 2,
    API_CODE_CheckBatteryInfo: 6,
    API_CODE_GetAFIlluminator: 1,
    API_CODE_GetAFMode: 2,
    API_CODE_GetAFStatus: 1,
    API_CODE_GetBlackImageTone: 1,
    API_CODE_GetCaptureDelay: 1,
    API_CODE_GetClarityMode: 1,
    API_CODE_GetColorChromeBlue: 1,
    API_CODE_GetColorMode: 1,
    API_CODE_GetColorSpace: 1,
    API_CODE_GetCommandDialStatus: 4,
    API_CODE_GetComment: 1,
    API_CODE_GetCopyright: 2,
    API_CODE_GetCropMode: 2,
    API_CODE_GetCustomWBArea: 2,
    API_CODE_GetDateTime: 6,
    API_CODE_GetDetectedFaceFrame: 2,
    API_CODE_GetEyeAFMode: 1,
    API_CODE_GetFaceDetectionMode: 1,
    API_CODE_GetFilenamePrefix: 2,
    API_CODE_GetFilmSimulationMode: 1,
    API_CODE_GetFocusArea: 2,
    API_CODE_GetFocusCheckMode: 1,
    API_CODE_GetFocusLimiterIndicator: 1,
    API_CODE_GetFocusLimiterMode: 1,
    API_CODE_GetFocusLimiterRange: 2,
    API_CODE_GetFocusMode: 1,
    API_CODE_GetFocusPoints: 1,
    API_CODE_GetFocusPos: 1,
    API_CODE_GetFullTimeManualFocus: 1,
    API_CODE_GetFunctionLock: 1,
    API_CODE_GetGrainEffect: 1,
    API_CODE_GetHighLightTone: 1,
    API_CODE_GetISMode: 1,
    API_CODE_GetImageQuality: 1,
    API_CODE_GetImageSize: 1,
    API_CODE_GetInstantAFMode: 1,
    API_CODE_GetInterlockAEAFArea: 1,
    API_CODE_GetLMOMode: 1,
    API_CODE_GetLensISSwitch: 1,
    API_CODE_GetLiveViewImageQuality: 1,
    API_CODE_GetLiveViewImageSize: 1,
    API_CODE_GetLongExposureNR: 1,
    API_CODE_GetMFAssistMode: 1,
    API_CODE_GetMediaCapacity: 5,
    API_CODE_GetMediaRecord: 1,
    API_CODE_GetMediaStatus: 2,
    API_CODE_GetMonochromaticColor: 2,
    API_CODE_GetNoiseReduction: 1,
    API_CODE_GetPreAFMode: 1,
    API_CODE_GetRAWCompression: 1,
    API_CODE_GetShadowTone: 1,
    API_CODE_GetShadowing: 1,
    API_CODE_GetSharpness: 1,
    API_CODE_GetShutterCount: 3,
    API_CODE_GetShutterPriorityMode: 2,
    API_CODE_GetSmoothSkinEffect: 1,
    API_CODE_GetThroughImageZoom: 1,
    API_CODE_GetWhiteBalanceTune: 3,
    API_CODE_GetWideDynamicRange: 1,
    API_CODE_ResetSetting: 1,
    API_CODE_SetAFIlluminator: 1,
    API_CODE_SetAFMode: 2,
    API_CODE_SetBlackImageTone: 1,
    API_CODE_SetCaptureDelay: 1,
    API_CODE_SetClarityMode: 1,
    API_CODE_SetColorChromeBlue: 1,
    API_CODE_SetColorMode: 1,
    API_CODE_SetColorSpace: 1,
    API_CODE_SetComment: 1,
    API_CODE_SetCopyright: 2,
    API_CODE_SetCropMode: 1,
    API_CODE_SetCustomWBArea: 2,
    API_CODE_SetDateTime: 6,
    API_CODE_SetDetectedFaceFrame: 1,
    API_CODE_SetEyeAFMode: 1,
    API_CODE_SetFaceDetectionMode: 1,
    API_CODE_SetFilenamePrefix: 2,
    API_CODE_SetFilmSimulationMode: 1,
    API_CODE_SetFocusArea: 2,
    API_CODE_SetFocusCheckMode: 1,
    API_CODE_SetFocusLimiterMode: 1,
    API_CODE_SetFocusLimiterPos: 2,
    API_CODE_SetFocusMode: 1,
    API_CODE_SetFocusPoints: 1,
    API_CODE_SetFocusPos: 1,
    API_CODE_SetFullTimeManualFocus: 1,
    API_CODE_SetFunctionLock: 1,
    API_CODE_SetGrainEffect: 1,
    API_CODE_SetHighLightTone: 1,
    API_CODE_SetISMode: 1,
    API_CODE_SetImageQuality: 1,
    API_CODE_SetImageSize: 1,
    API_CODE_SetInstantAFMode: 1,
    API_CODE_SetInterlockAEAFArea: 1,
    API_CODE_SetLMOMode: 1,
    API_CODE_SetLensISSwitch: 1,
    API_CODE_SetLiveViewImageQuality: 1,
    API_CODE_SetLiveViewImageSize: 1,
    API_CODE_SetLongExposureNR: 1,
    API_CODE_SetMFAssistMode: 1,
    API_CODE_SetMediaRecord: 1,
    API_CODE_SetMonochromaticColor: 2,
    API_CODE_SetNoiseReduction: 1,
    API_CODE_SetPreAFMode: 1,
    API_CODE_SetRAWCompression: 1,
    API_CODE_SetShadowTone: 1,
    API_CODE_SetShadowing: 1,
    API_CODE_SetSharpness: 1,
    API_CODE_SetShutterPriorityMode: 2,
    API_CODE_SetSmoothSkinEffect: 1,
    API_CODE_SetThroughImageZoom: 1,
    API_CODE_SetWhiteBalanceTune: 3,
    API_CODE_SetWideDynamicRange: 1,
    API_CODE_StartLiveView: 0,
    API_CODE_StopLiveView: 0,
}


def api_param(api_code: int) -> int:
    """The parameter number this API expects, defaulting to 0.

    0 is the right answer for the handful that take it (StartLiveView and
    StopLiveView among them) and the only answer available for an API missing
    from the table, which is where the wrapper was before.
    """
    return API_PARAM.get(api_code, 0)


# --------------------------------------------------------------------------
# Battery, media and shutter count
# --------------------------------------------------------------------------
# From HEADERS/XAPIOpt.H.  The three APIs these belong to were called with the
# wrong number of arguments and had never once returned a real answer.

#: Which card slot to ask about.  The X-T4 has two.
ITEM_MEDIASLOT1 = 1
ITEM_MEDIASLOT2 = 2

MEDIASTATUS_OK = 0x0001
MEDIASTATUS_WRITEPROTECTED = 0x0002
MEDIASTATUS_NOCARD = 0x0003
MEDIASTATUS_UNFORMATTED = 0x0004
MEDIASTATUS_ERROR = 0x0005
MEDIASTATUS_MAXNO = 0x0006
MEDIASTATUS_FULL = 0x0007
MEDIASTATUS_ACCESSING = 0x0008
MEDIASTATUS_INCOMPATIBLE = 0x0009

MEDIASTATUS_NAMES: dict[int, str] = {
    MEDIASTATUS_OK: "OK",
    MEDIASTATUS_WRITEPROTECTED: "write protected",
    MEDIASTATUS_NOCARD: "no card",
    MEDIASTATUS_UNFORMATTED: "unformatted",
    MEDIASTATUS_ERROR: "card error",
    MEDIASTATUS_MAXNO: "frame numbering exhausted (9999)",
    MEDIASTATUS_FULL: "card full",
    MEDIASTATUS_ACCESSING: "being written to",
    MEDIASTATUS_INCOMPATIBLE: "incompatible card",
}

#: Anything here means the next frame has nowhere to go.
MEDIASTATUS_CANNOT_WRITE = frozenset((
    MEDIASTATUS_WRITEPROTECTED,
    MEDIASTATUS_NOCARD,
    MEDIASTATUS_UNFORMATTED,
    MEDIASTATUS_ERROR,
    MEDIASTATUS_MAXNO,
    MEDIASTATUS_FULL,
    MEDIASTATUS_INCOMPATIBLE,
))

POWERCAPACITY_EMPTY = 0x0000
POWERCAPACITY_END = 0x0001
POWERCAPACITY_PREEND = 0x0002
POWERCAPACITY_HALF = 0x0003
POWERCAPACITY_FULL = 0x0004
POWERCAPACITY_HIGH = 0x0005
POWERCAPACITY_PREEND5 = 0x0007
POWERCAPACITY_20 = 0x0008
POWERCAPACITY_40 = 0x0009
POWERCAPACITY_60 = 0x000A
POWERCAPACITY_80 = 0x000B
POWERCAPACITY_100 = 0x000C
POWERCAPACITY_DC_CHARGE = 0x000D
POWERCAPACITY_FULL_CHARGE = 0x000E
POWERCAPACITY_CHARGING_ERROR = 0x000F
POWERCAPACITY_CAPACITY_UNKNOWN = 0x0010
POWERCAPACITY_DC = 0x00FF

POWERCAPACITY_NAMES: dict[int, str] = {
    POWERCAPACITY_EMPTY: "empty",
    POWERCAPACITY_END: "flat",
    POWERCAPACITY_PREEND: "nearly flat",
    POWERCAPACITY_HALF: "half",
    POWERCAPACITY_FULL: "full",
    POWERCAPACITY_HIGH: "high",
    POWERCAPACITY_PREEND5: "under 20%",
    POWERCAPACITY_20: "20%",
    POWERCAPACITY_40: "40%",
    POWERCAPACITY_60: "60%",
    POWERCAPACITY_80: "80%",
    POWERCAPACITY_100: "100%",
    POWERCAPACITY_DC: "on mains",
    POWERCAPACITY_DC_CHARGE: "charging",
    POWERCAPACITY_FULL_CHARGE: "charged",
    POWERCAPACITY_CHARGING_ERROR: "charging error",
    POWERCAPACITY_CAPACITY_UNKNOWN: "unknown",
}

#: Roughly what a level means as a percentage, for a progress bar.  The body
#: reports a coarse level rather than a number, so this cannot be finer.
POWERCAPACITY_PERCENT: dict[int, int] = {
    POWERCAPACITY_EMPTY: 0,
    POWERCAPACITY_END: 5,
    POWERCAPACITY_PREEND: 10,
    POWERCAPACITY_PREEND5: 15,
    POWERCAPACITY_20: 20,
    POWERCAPACITY_40: 40,
    POWERCAPACITY_HALF: 50,
    POWERCAPACITY_60: 60,
    POWERCAPACITY_80: 80,
    POWERCAPACITY_HIGH: 85,
    POWERCAPACITY_FULL: 100,
    POWERCAPACITY_100: 100,
    POWERCAPACITY_FULL_CHARGE: 100,
}

#: Levels at which a body should not be trusted to last a totality.
POWERCAPACITY_LOW = frozenset((
    POWERCAPACITY_EMPTY, POWERCAPACITY_END, POWERCAPACITY_PREEND,
    POWERCAPACITY_PREEND5, POWERCAPACITY_20,
))
