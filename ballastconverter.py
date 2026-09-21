#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ballastconverter.py – negative -> positive exactly following the ColorNeg mode of ColorPerfect (ColorPerfect64.8bf, build 2018-08-28).

Reconstructed from the decompiled functions:
  0x10011e40  histogram (clamp 16-bit codes to 0..32767, 8-bit values * 128)
  0x10003fc0  lin[] table: lin[i] = decode(i / 32768)      (decode = GammaC curve, identity for "L")
  0x10002c30  lower percentile   (lo_c)
  0x10002a00  upper percentile   (hi_c)
  0x1002ef70  film gammas from the built-in table
  0x100182e0  LUT_c[i] = lo_c^g_c * lin[i]^(-g_c),  BPoint = min_c (lo_c/hi_c)^g_c,  BPColor_c = (lo_c/hi_c)^g_c - BPoint
  0x1000aa20  Pixel: p_c = LUT_c[code] - BPoint - BPColor_c ; p_c *= 2^(-Black) * CC_c ; p_c = max(p_c, 1.05/32768)
  0x10003a50  encoding into the output GammaC curve, * 32768, truncated (not rounded)

Only the steps that belong to the actual conversion are included. Gamma/White/Zones/Saturation/SmartClip are deliberately left out.

Own addition, not part of the plugin: --datasheet-curve. For films with a curve file in the folder 'curves'
(manufacturer's characteristic curves, Status M density over log exposure) the toe and shoulder of the datasheet
curve are applied on top of the straight-line (single gamma) model. White and black anchor stay exactly where the
plain model puts them; only the shape in between changes. Off by default, the result is then bit-identical.

Requires: numpy, tifffile   (pip install numpy tifffile)

Examples:
  python3 ballastconverter.py scan.tif positive.tif --film "Kodak/Portra 400NC"
  python3 ballastconverter.py scan.tif positive.tif --gammas 1.89 1.82 1.64
  python3 ballastconverter.py scan.tif positive.tif --film Generic        (1.70 / 1.63 / 1.48, median of the table)
  python3 ballastconverter.py scan.fff positive.tif --film Generic --in-curve "icc:Flextight X5 & 949.icc" --stats-crop 700 500 7200 10600
      (Imacon 3f: linearization via the scanner profile; percentiles only from the image area, output complete)
  python3 ballastconverter.py --list-films
"""
import argparse
import os
import re
import sys
import numpy as np

# (Manufacturer, film name): (gR, gG, gB)  -- decoded from the table at 0x100784f0
FILMS = {
    # Not a plugin entry: median of the 310 built-in films (R 1.692, G 1.626, B 1.452, rounded),
    # as a neutral starting point for unknown films. The plugin itself only has 'B&W Start' (1, 1, 1).
    ('Generic', 'Generic'): (1.70, 1.63, 1.48),
    ('Generic', 'B&W Start'): (1.0, 1.0, 1.0),
    ('Agfa', 'ASP 400 X PE1 / PE0'): (1.204500, 1.264500, 1.013500),
    ('Agfa', 'Agfacolor 100 {1982}'): (2.171000, 1.548000, 1.393000),
    ('Agfa', 'Agfacolor 80S {1976}'): (1.043000, 1.039000, 0.843000),
    ('Agfa', 'Agfacolor CN 14 {1960}'): (1.329500, 1.336500, 1.336500),
    ('Agfa', 'Agfacolor CN 17 U {1974}'): (1.021000, 0.861000, 0.829000),
    ('Agfa', 'Agfacolor CN 17 {1960}'): (1.285500, 1.291500, 1.285500),
    ('Agfa', 'Agfacolor CNS {1978}'): (1.043000, 1.032000, 0.844000),
    ('Agfa', 'Agfacolor pocket special {1974}'): (1.045000, 1.037000, 0.844000),
    ('Agfa', 'Aviphot Color N800'): (1.881000, 1.778000, 1.638000),
    ('Agfa', 'Aviphot Color N800 {4 min.}'): (1.880000, 1.800000, 1.658000),
    ('Agfa', 'Aviphot Color X100'): (1.707000, 1.633000, 1.313000),
    ('Agfa', 'Aviphot Color X100 {4 min.}'): (1.383500, 1.413500, 1.116500),
    ('Agfa', 'Aviphot Color X100 {5.2 min.}'): (1.159000, 0.967000, 0.814000),
    ('Agfa', 'Aviphot Color X400'): (1.182000, 1.231000, 0.974000),
    ('Agfa', 'Aviphot Color X400 {4 min.}'): (1.177000, 1.225000, 0.960000),
    ('Agfa', 'Futura 100'): (1.717000, 1.738000, 1.568000),
    ('Agfa', 'Futura 200'): (1.723000, 1.736000, 1.564000),
    ('Agfa', 'Futura 400'): (1.657000, 1.673000, 1.519000),
    ('Agfa', 'Futura II 100'): (1.680000, 1.610000, 1.480000),
    ('Agfa', 'Futura II 200'): (1.630000, 1.620000, 1.490000),
    ('Agfa', 'Futura II 400'): (1.630000, 1.630000, 1.470000),
    ('Agfa', 'HDC 100 plus'): (1.578000, 1.605000, 1.469000),
    ('Agfa', 'HDC 200 plus'): (1.643000, 1.668000, 1.520000),
    ('Agfa', 'HDC 400 plus'): (1.694000, 1.708000, 1.553000),
    ('Agfa', 'Optima 100'): (1.608000, 1.585000, 1.483000),
    ('Agfa', 'Optima 200'): (1.837000, 1.813000, 1.680000),
    ('Agfa', 'Optima 400'): (1.648000, 1.632000, 1.491000),
    ('Agfa', 'Optima II 100'): (1.650000, 1.650000, 1.490000),
    ('Agfa', 'Optima II 200'): (1.680000, 1.710000, 1.560000),
    ('Agfa', 'Optima II 400'): (1.750000, 1.780000, 1.570000),
    ('Agfa', 'Portrait 160'): (1.998000, 1.793000, 1.664000),
    ('Agfa', 'Portrait XPS 160'): (2.080000, 1.820000, 1.680000),
    ('Agfa', 'Ultra  50'): (1.720000, 1.580000, 1.340000),
    ('Agfa', 'Ultra 100'): (1.598000, 1.582000, 1.466000),
    ('Agfa', 'Vista 100'): (1.640000, 1.630000, 1.530000),
    ('Agfa', 'Vista 200'): (1.820000, 1.790000, 1.690000),
    ('Agfa', 'Vista 400'): (1.640000, 1.630000, 1.490000),
    ('Agfa', 'Vista 800'): (1.600000, 1.550000, 1.470000),
    ('Agfa', 'XRG 100'): (1.556000, 1.426000, 1.314000),
    ('AgfaPhoto', 'APS star 200'): (1.247000, 1.253000, 1.160000),
    ('AgfaPhoto', 'Vista 100'): (1.526500, 1.544500, 1.305500),
    ('AgfaPhoto', 'Vista 200'): (1.369000, 1.429000, 1.308000),
    ('AgfaPhoto', 'Vista 400'): (1.420000, 1.458000, 1.287000),
    ('AgfaPhoto', 'Vista plus 200'): (1.654500, 1.509500, 1.430500),
    ('AgfaPhoto', 'Vista plus 400'): (1.653000, 1.508000, 1.434000),
    ('China Lucky', 'Luckycolor Super GBR200'): (2.162000, 1.604000, 1.480000),
    ('China Lucky', 'Luckycolor Super GBR400'): (2.102000, 1.596000, 1.471000),
    ('Ferrania', 'Solaris FG Plus 100'): (1.964000, 1.804000, 1.675000),
    ('Ferrania', 'Solaris FG Plus 200'): (2.012000, 1.814000, 1.697000),
    ('Ferrania', 'Solaris FG Plus 400'): (1.931000, 1.909000, 1.835000),
    ('Ferrania', 'Solaris FG Plus 800'): (1.938000, 1.916000, 1.834000),
    ('Fuji', '160 NC'): (1.573500, 1.545500, 1.353500),
    ('Fuji', '160 NL'): (1.713000, 1.603000, 1.429000),
    ('Fuji', 'Fujicolor 100'): (1.282000, 1.340000, 1.255000),
    ('Fuji', 'HR 100 [CN] {1984}'): (1.282000, 1.202000, 1.042000),
    ('Fuji', 'HR 1600 [CU] {1984}'): (1.486500, 1.476500, 1.361500),
    ('Fuji', 'HR 200 [CA] {1984}'): (1.451000, 1.468000, 1.270000),
    ('Fuji', 'HR 400 [CH] {1984}'): (1.454000, 1.513000, 1.370000),
    ('Fuji', 'NHG II 800'): (1.432000, 1.301000, 1.271000),
    ('Fuji', 'NPC 160 [901]'): (1.633000, 1.701000, 1.889000),
    ('Fuji', 'NPC 160 [925]'): (1.588000, 1.571000, 1.857000),
    ('Fuji', 'NPH 400 {New}'): (1.670000, 1.719000, 1.874000),
    ('Fuji', 'NPH 400 {Old}'): (1.383000, 1.167000, 1.284000),
    ('Fuji', 'NPL 160'): (1.760000, 1.680000, 1.450000),
    ('Fuji', 'NPL 160 Professional'): (1.760000, 1.680000, 1.450000),
    ('Fuji', 'NPS 160'): (1.740000, 1.810000, 1.600000),
    ('Fuji', 'NPZ 800'): (1.400000, 1.560000, 1.700000),
    ('Fuji', 'Natura 1600'): (1.428000, 1.362000, 1.287000),
    ('Fuji', 'New Pro 400 [NP400N]'): (1.426000, 1.580000, 1.638000),
    ('Fuji', 'Nexia APS 400 [DH]'): (1.480000, 1.380000, 1.400000),
    ('Fuji', 'Nexia APS 400 {JP}'): (1.379500, 1.358500, 1.303500),
    ('Fuji', 'Nexia APS 800 [DZ]'): (1.270000, 1.240000, 1.380000),
    ('Fuji', 'Nexia APS 800 {JP}'): (1.325000, 1.354000, 1.306000),
    ('Fuji', 'Nexia APS A200 [DA]'): (1.660000, 1.520000, 1.480000),
    ('Fuji', 'Nexia APS D100 [DN]'): (1.487000, 1.319000, 1.335000),
    ('Fuji', 'Nexia APS H400 [DH]'): (1.411000, 1.323000, 1.337000),
    ('Fuji', 'PRESS  400 [P-400 CH]'): (1.550000, 1.450000, 1.380000),
    ('Fuji', 'PRESS  800 [P-800 CZ]'): (1.370000, 1.280000, 1.270000),
    ('Fuji', 'PRESS 1600 [P-1600 CU]'): (1.429000, 1.364000, 1.295000),
    ('Fuji', 'PRO 160 NC [PN160NC]'): (1.504000, 1.599000, 1.560000),
    ('Fuji', 'PRO 160 NH [PN160NH]'): (1.482000, 1.654000, 1.738000),
    ('Fuji', 'PRO 160 NS [PN160NS]'): (1.687000, 1.862000, 1.803000),
    ('Fuji', 'PRO 160C'): (1.600000, 1.620000, 1.640000),
    ('Fuji', 'PRO 160S'): (1.840000, 1.840000, 1.850000),
    ('Fuji', 'PRO 400H'): (1.760000, 1.820000, 1.930000),
    ('Fuji', 'PRO 800'): (1.497000, 1.646000, 1.756000),
    ('Fuji', 'PRO 800Z'): (1.450000, 1.630000, 1.790000),
    ('Fuji', 'Reala ACE'): (1.493000, 1.474000, 1.336000),
    ('Fuji', 'Super HG 1600 [CU]'): (1.491000, 1.261000, 1.172000),
    ('Fuji', 'Superia  100 Pro Pack'): (1.280000, 1.230000, 1.210000),
    ('Fuji', 'Superia  100 [CN - 901]'): (1.327000, 1.235000, 1.250000),
    ('Fuji', 'Superia  100 [CN - E01]'): (1.360000, 1.199000, 1.305000),
    ('Fuji', 'Superia  100 [CN - E51]'): (1.215000, 1.186000, 1.181000),
    ('Fuji', 'Superia  100 [CN]'): (1.340000, 1.290000, 1.230000),
    ('Fuji', 'Superia  200 Pro Pack'): (1.350000, 1.250000, 1.330000),
    ('Fuji', 'Superia  200 [CA - 501]'): (1.346000, 1.239000, 1.292000),
    ('Fuji', 'Superia  200 [CA - 571]'): (1.644000, 1.500000, 1.452000),
    ('Fuji', 'Superia  200 [CA - F01]'): (1.347000, 1.221000, 1.319000),
    ('Fuji', 'Superia  200 [CA - F51]'): (1.341000, 1.235000, 1.290000),
    ('Fuji', 'Superia  200 [CA]'): (1.390000, 1.290000, 1.380000),
    ('Fuji', 'Superia  400 - Evidence'): (1.450000, 1.380000, 1.340000),
    ('Fuji', 'Superia  400 [CH - G01]'): (1.423000, 1.368000, 1.315000),
    ('Fuji', 'Superia  400 [CH - G51]'): (1.375000, 1.191000, 1.271000),
    ('Fuji', 'Superia  400 [CH - W01]'): (1.439000, 1.375000, 1.321000),
    ('Fuji', 'Superia  800 [CZ - L51]'): (1.395000, 1.228000, 1.320000),
    ('Fuji', 'Superia 1600 [CU - P51]'): (1.410000, 1.352000, 1.277000),
    ('Fuji', 'Superia 1600 [CU - R01]'): (1.316000, 1.377000, 1.262000),
    ('Fuji', 'Superia 1600 [CU]'): (1.420000, 1.350000, 1.270000),
    ('Fuji', 'Superia Premium 400'): (1.446500, 1.459500, 1.386500),
    ('Fuji', 'Superia Reala [CS]'): (1.520000, 1.530000, 1.550000),
    ('Fuji', 'Superia Venus 400'): (1.580000, 1.477000, 1.392000),
    ('Fuji', 'Superia Venus 800'): (1.381000, 1.352000, 1.300000),
    ('Fuji', 'Superia X-TRA 400  [CH - U01A]'): (1.636000, 1.495000, 1.430000),
    ('Fuji', 'Superia X-TRA 400 [CH - H01]'): (1.629000, 1.495000, 1.427000),
    ('Fuji', 'Superia X-TRA 400 [CH - H74]'): (1.626000, 1.438000, 1.415000),
    ('Fuji', 'Superia X-TRA 400 [CH - X01]'): (1.544000, 1.457000, 1.361000),
    ('Fuji', 'Superia X-TRA 400 [CH]'): (1.550000, 1.450000, 1.380000),
    ('Fuji', 'Superia X-TRA 800 [CZ - L01]'): (1.318000, 1.263000, 1.263000),
    ('Fuji', 'Superia X-TRA 800 [CZ]'): (1.370000, 1.280000, 1.270000),
    ('Fuji', 'True Definition 400 [TD400 CH]'): (1.870000, 1.990000, 2.170000),
    ('Fuji {Movie Stock}', 'A 250'): (1.912000, 1.912000, 1.726000),
    ('Fuji {Movie Stock}', 'Eterna 250 [FN53]'): (2.145500, 1.901500, 1.805500),
    ('Fuji {Movie Stock}', 'Eterna 250D [FN63]'): (2.163500, 1.955500, 1.783500),
    ('Fuji {Movie Stock}', 'Eterna 400 [FN83]'): (2.514000, 2.205000, 1.935000),
    ('Fuji {Movie Stock}', 'Eterna 500 [FN73]'): (2.150000, 1.843000, 1.743000),
    ('Fuji {Movie Stock}', 'Eterna Vivid 160 [FN43]'): (2.072500, 1.810500, 1.634500),
    ('Fuji {Movie Stock}', 'Eterna Vivid 250D [FN46]'): (2.140500, 1.817500, 1.775500),
    ('Fuji {Movie Stock}', 'Eterna Vivid 500 [FN47]'): (2.069000, 1.688000, 1.624000),
    ('Fuji {Movie Stock}', 'F-125 [FN32]'): (1.986000, 1.443000, 1.600000),
    ('Fuji {Movie Stock}', 'F-250 [FN52]'): (1.951500, 1.872500, 1.642500),
    ('Fuji {Movie Stock}', 'F-400 [FN82]'): (2.484500, 2.239500, 1.939500),
    ('Fuji {Movie Stock}', 'F-500 [FN72]'): (1.916000, 1.694000, 1.583000),
    ('Fuji {Movie Stock}', 'F-64D [FN22]'): (1.873000, 1.776000, 1.689000),
    ('Fuji {Movie Stock}', 'Reala 500D [FN92]'): (2.171000, 1.927000, 1.768000),
    ('Kodak', 'ADVANTiX 100'): (1.793000, 1.713000, 1.566000),
    ('Kodak', 'ADVANTiX 200'): (1.809000, 1.708000, 1.551000),
    ('Kodak', 'ADVANTiX 400'): (1.694000, 1.627000, 1.493000),
    ('Kodak', 'ADVANTiX High Definition 200'): (1.850000, 1.740000, 1.530000),
    ('Kodak', 'ADVANTiX Versatility'): (1.810000, 1.720000, 1.530000),
    ('Kodak', 'Aerocolor 2445'): (1.120000, 1.150000, 1.150000),
    ('Kodak', 'Aerocolor HS SO-846 {HC Dev}'): (1.315000, 1.228000, 1.129000),
    ('Kodak', 'Aerocolor HS SO-846 {LC Dev}'): (1.671000, 1.661000, 1.478000),
    ('Kodak', 'Aerocolor HS SO-846 {MC Dev}'): (1.206000, 1.329000, 1.242000),
    ('Kodak', 'Aerocolor III [2444] {HC Dev}'): (1.177000, 1.045000, 1.135000),
    ('Kodak', 'Aerocolor III [2444] {LC Dev}'): (1.703000, 1.507000, 1.531000),
    ('Kodak', 'Aerocolor III [2444] {MC Dev}'): (1.380000, 1.247000, 1.304000),
    ('Kodak', 'Bright Sun & Flash GB 200'): (1.761000, 1.666000, 1.420000),
    ('Kodak', 'Bright Sun GA 100'): (1.761000, 1.661000, 1.416000),
    ('Kodak', 'Ektapress 100 [5115 PJA]'): (1.753000, 1.680000, 1.452000),
    ('Kodak', 'Ektapress Multispeed [5640 PJM]'): (1.680000, 1.612000, 1.390000),
    ('Kodak', 'Ektapress PJ100'): (1.815000, 1.752000, 1.514000),
    ('Kodak', 'Ektapress PJ400'): (1.682000, 1.622000, 1.396000),
    ('Kodak', 'Ektapress PJ400 {Push 1}'): (1.465000, 1.408000, 1.179000),
    ('Kodak', 'Ektapress PJ400 {Push 2}'): (1.440000, 1.300000, 1.093000),
    ('Kodak', 'Ektapress PJ800'): (1.753000, 1.689000, 1.435000),
    ('Kodak', 'Ektapress PJ800 {Push 1}'): (1.513000, 1.491000, 1.310000),
    ('Kodak', 'Ektapress PJ800 {Push 2}'): (1.358000, 1.269000, 1.236000),
    ('Kodak', 'Ektapress Plus 1600 [5030 PJC]'): (1.745000, 1.652000, 1.392000),
    ('Kodak', 'Ektapress Plus 1600 [5030 PJC] {Push 1}'): (1.603000, 1.522000, 1.335000),
    ('Kodak', 'Ektapress Plus 1600 [5030 PJC] {Push 2}'): (1.358000, 1.298000, 1.213000),
    ('Kodak', 'Ektar 100 [5110] [6110] {2008}'): (1.840000, 1.840000, 1.560000),
    ('Kodak', 'Elite Color 200'): (1.810000, 1.706000, 1.506000),
    ('Kodak', 'Elite Color 400'): (1.756000, 1.696000, 1.476000),
    ('Kodak', 'Elite Color 400 {Push 1}'): (1.570000, 1.480000, 1.330000),
    ('Kodak', 'Farbwelt 100 [FA 100-6]'): (1.819000, 1.683000, 1.420000),
    ('Kodak', 'Farbwelt 100 {2007}'): (1.846000, 1.765000, 1.612000),
    ('Kodak', 'Farbwelt 200 [FB 200-6]'): (1.598000, 1.611000, 1.445000),
    ('Kodak', 'Farbwelt 200 {2007}'): (1.831000, 1.775000, 1.612000),
    ('Kodak', 'Farbwelt 400 [FC 400-6]'): (1.709000, 1.629000, 1.368000),
    ('Kodak', 'Farbwelt 400 {2007}'): (1.765000, 1.730000, 1.523000),
    ('Kodak', 'Farbwelt 800 [FT 800-3]'): (1.777000, 1.633000, 1.508000),
    ('Kodak', 'Gold 100 [GA 100-6]'): (1.760000, 1.645000, 1.390000),
    ('Kodak', 'Gold 100 {1998}'): (1.760000, 1.659000, 1.420000),
    ('Kodak', 'Gold 100 {2007}'): (1.846000, 1.765000, 1.612000),
    ('Kodak', 'Gold 200 [GB 200-6]'): (1.523000, 1.584000, 1.428000),
    ('Kodak', 'Gold 200 {1998}'): (1.765000, 1.661000, 1.415000),
    ('Kodak', 'Gold 200 {2007}'): (1.831000, 1.775000, 1.612000),
    ('Kodak', 'Gold 800 Zoom GT [800-2]'): (1.792000, 1.699000, 1.408000),
    ('Kodak', 'Gold GA 100'): (1.770000, 1.660000, 1.420000),
    ('Kodak', 'Gold GB 200'): (1.760000, 1.670000, 1.430000),
    ('Kodak', 'Gold MAX 400'): (1.708000, 1.659000, 1.411000),
    ('Kodak', 'Gold MAX 800'): (1.730000, 1.673000, 1.415000),
    ('Kodak', 'Gold Ultra 400 GC [400-6]'): (1.679000, 1.583000, 1.354000),
    ('Kodak', 'Hawkeye'): (1.797000, 1.720000, 1.500000),
    ('Kodak', 'High Definition 200 Film [3992 HD2]'): (1.860000, 1.740000, 1.540000),
    ('Kodak', 'High Definition 400 Film [3926 HDC]'): (1.840000, 1.750000, 1.530000),
    ('Kodak', 'Kodacolor II'): (1.719000, 1.586000, 1.470000),
    ('Kodak', 'Law Enforcement LE100'): (1.808000, 1.733000, 1.502000),
    ('Kodak', 'Law Enforcement LE400'): (1.695000, 1.624000, 1.398000),
    ('Kodak', 'Law Enforcement LE400 {Push 1}'): (1.467000, 1.415000, 1.175000),
    ('Kodak', 'Law Enforcement LE400 {Push 2}'): (1.449000, 1.300000, 1.082000),
    ('Kodak', 'Law Enforcement LE800'): (1.678000, 1.623000, 1.405000),
    ('Kodak', 'Law Enforcement LE800 {Push 1}'): (1.466000, 1.423000, 1.296000),
    ('Kodak', 'Law Enforcement LE800 {Push 2}'): (1.364000, 1.301000, 1.241000),
    ('Kodak', 'MAX GC 400'): (1.760000, 1.719000, 1.575000),
    ('Kodak', 'MAX Versatility'): (1.810000, 1.790000, 1.540000),
    ('Kodak', 'MAX Versatility Plus [5148 GT]'): (1.840000, 1.880000, 1.590000),
    ('Kodak', 'Portra 100T'): (1.707000, 1.641000, 1.487000),
    ('Kodak', 'Portra 160 [4059] [5059] [6059]'): (1.916000, 1.829000, 1.665000),
    ('Kodak', 'Portra 160NC'): (1.880000, 1.800000, 1.650000),
    ('Kodak', 'Portra 160NC {2008}'): (1.832000, 1.790000, 1.562000),
    ('Kodak', 'Portra 160VC'): (1.720000, 1.650000, 1.490000),
    ('Kodak', 'Portra 160VC {2008}'): (1.734000, 1.729000, 1.472000),
    ('Kodak', 'Portra 400 [4056] [5056] [6056]'): (1.834000, 1.804000, 1.567000),
    # Own fit from the Kodak data sheet E-4050 (Feb 2016): reciprocal of the Status-M characteristic curve slope,
    # range log H -2.2..-0.2 (normal scene around log H ref -1.44). See recherche/Portra400_Datenblatt.md / portra400_kennlinien.txt.
    # Practically identical to the plugin entry above -> the plugin value evidently comes from the same curve.
    ('Kodak', 'Portra 400 (2026)'): (1.837, 1.811, 1.570),
    # Scanner-specific fit (2026-09-16): red and blue fitted at fixed green so that the tonal-scale colour balance is
    # consistent across seven Portra 400 scans from a Flextight X5 (3f, --in-curve icc: with the profile's TRC tags,
    # 0.1 % percentiles, no datasheet curve). Only blue differs materially from the data sheet (1.91 instead of 1.57):
    # the scanner's blue channel sees the yellow dye with less contrast than Status M. See recherche/gammafit/Auswertung.md.
    ('Kodak', 'Portra 400 (X5 fit)'): (1.80, 1.811, 1.91),
    # Second scanner-specific fit (2026-09-16): red and blue fitted on 15 user-confirmed neutral surfaces (asphalt,
    # concrete, white paint, white cotton, black rubber) across the same seven scans, per-scan grey pipette allowed.
    # Both red and blue show a crossover against the data sheet: red 1.70 (darker surfaces lacked red), blue 1.95.
    ('Kodak', 'Portra 400 (X5 neutral)'): (1.70, 1.811, 1.95),
    # Third scanner-specific fit (2026-09-18), after the Fuji Frontier patents (US6160634): grey-balance line of the
    # film learned from all pixels of the same seven scans (red and blue density against green density, pixels near
    # the running mean only). The line is straight within 0.03 D; its slopes give red 1.90 and blue 1.85.
    # See recherche/frontier/Auswertung.md.
    ('Kodak', 'Portra 400 (X5 balance)'): (1.90, 1.811, 1.85),
    ('Kodak', 'Portra 400NC'): (1.890000, 1.820000, 1.640000),
    ('Kodak', 'Portra 400NC {2008}'): (1.843000, 1.794000, 1.566000),
    ('Kodak', 'Portra 400VC'): (1.710000, 1.650000, 1.490000),
    ('Kodak', 'Portra 400VC {2008}'): (1.746000, 1.721000, 1.492000),
    ('Kodak', 'Portra 800'): (1.760000, 1.750000, 1.490000),
    ('Kodak', 'Portra 800   {Push 1}'): (1.530000, 1.480000, 1.320000),
    ('Kodak', 'Portra 800   {Push 2}'): (1.320000, 1.310000, 1.170000),
    ('Kodak', 'Portra 800  {2008}'): (1.927000, 1.851000, 1.653000),
    ('Kodak', 'Portra 800 {2008 Push 1}'): (1.567000, 1.589000, 1.375000),
    ('Kodak', 'Portra 800 {2008 Push 2}'): (1.444000, 1.423000, 1.265000),
    ('Kodak', 'Pro  100 [PRN]'): (1.723000, 1.548000, 1.490000),
    ('Kodak', 'Pro  100T [PRT]'): (1.779000, 1.609000, 1.517000),
    ('Kodak', 'Pro  400 MC [PMC]'): (1.876000, 1.840000, 1.651000),
    ('Kodak', 'Pro  400 [PPF]'): (1.661000, 1.629000, 1.348000),
    ('Kodak', 'Pro 1000 [PMZ]'): (1.715000, 1.621000, 1.385000),
    ('Kodak', 'Pro Image 100'): (1.769000, 1.669000, 1.422000),
    ('Kodak', 'Profoto 100'): (1.763000, 1.665000, 1.416000),
    ('Kodak', 'Royal Gold   25 [RZ]'): (1.779000, 1.651000, 1.466000),
    ('Kodak', 'Royal Gold  100 [RA 100-2]'): (1.774000, 1.687000, 1.471000),
    ('Kodak', 'Royal Gold  200 [RB 200-2] {1998}'): (1.827000, 1.740000, 1.456000),
    ('Kodak', 'Royal Gold  200 [RB] {2002}'): (1.829500, 1.716500, 1.530500),
    ('Kodak', 'Royal Gold  400 [RC 400-2] {1998}'): (1.671000, 1.612000, 1.402000),
    ('Kodak', 'Royal Gold  400 [RC] {2002}'): (1.790500, 1.724500, 1.490500),
    ('Kodak', 'Royal Gold 1000 [RF]'): (1.730000, 1.619000, 1.372000),
    ('Kodak', 'Royal Supra 200'): (1.816000, 1.709000, 1.512000),
    ('Kodak', 'Royal Supra 400'): (1.798000, 1.717000, 1.506000),
    ('Kodak', 'Royal Supra 400 {Push 1}'): (1.620000, 1.482000, 1.315000),
    ('Kodak', 'Royal Supra 800'): (1.755000, 1.663000, 1.466000),
    ('Kodak', 'Royal Supra 800 {Push 1}'): (1.443000, 1.409000, 1.303000),
    ('Kodak', 'Royal Supra 800 {Push 2}'): (1.275000, 1.251000, 1.198000),
    ('Kodak', 'Supra 100'): (1.757000, 1.719000, 1.476000),
    ('Kodak', 'Supra 400'): (1.651000, 1.618000, 1.484000),
    ('Kodak', 'Supra 400 {Push 1}'): (1.480000, 1.368000, 1.280000),
    ('Kodak', 'Supra 800'): (1.766000, 1.687000, 1.516000),
    ('Kodak', 'Supra 800 {Push 1}'): (1.482000, 1.425000, 1.337000),
    ('Kodak', 'Supra 800 {Push 2}'): (1.299000, 1.261000, 1.233000),
    ('Kodak', 'T400 CN'): (1.702000, 1.654000, 1.412000),
    ('Kodak', 'Ultra'): (1.765000, 1.730000, 1.523000),
    ('Kodak', 'Ultra Color 100UC'): (1.890000, 1.770000, 1.560000),
    ('Kodak', 'Ultra Color 400UC'): (1.840000, 1.740000, 1.560000),
    ('Kodak', 'Ultra Color 400UC {Push 1}'): (1.617000, 1.478000, 1.320000),
    ('Kodak', 'Ultra Max 400'): (1.936000, 1.846000, 1.673000),
    ('Kodak', 'Ultra Max 800'): (1.770000, 1.699000, 1.519000),
    ('Kodak', 'Vericolor II Type L [6013] [4108]'): (1.364500, 1.416500, 1.395500),
    ('Kodak', 'Vericolor III Pro [5026] [6006] [4106]'): (1.690000, 1.537000, 1.453000),
    ('Kodak {Movie Stock}', '500T [5230] [7230]'): (2.109000, 1.824000, 1.891000),
    ('Kodak {Movie Stock}', 'Eastman CN Film 5247 {1980s}'): (1.905500, 1.705500, 1.745500),
    ('Kodak {Movie Stock}', 'Eastman CN Film 5297 {1980s}'): (1.870000, 1.700000, 1.670000),
    ('Kodak {Movie Stock}', 'Eastman EXR 100T [5248] [7248]'): (1.933000, 1.691000, 1.726000),
    ('Kodak {Movie Stock}', 'Eastman EXR 200T [5287] [7287]'): (2.076000, 1.926000, 1.954000),
    ('Kodak {Movie Stock}', 'Eastman EXR 200T [5293] [7293]'): (2.094500, 1.754500, 1.776500),
    ('Kodak {Movie Stock}', 'Eastman EXR 500T [5298]'): (1.939500, 1.697500, 1.704500),
    ('Kodak {Movie Stock}', 'Eastman EXR 50D [5245] [7245]'): (1.897500, 1.619500, 1.572500),
    ('Kodak {Movie Stock}', 'Primetime 640T [5620] [7620]'): (2.067000, 2.491000, 2.448000),
    ('Kodak {Movie Stock}', 'Vision 200T [5274] [7274]'): (2.122500, 1.787500, 1.698500),
    ('Kodak {Movie Stock}', 'Vision 250D [5246] [7246]'): (1.761500, 1.615500, 1.595500),
    ('Kodak {Movie Stock}', 'Vision 320T [5277] [7277]'): (2.173500, 1.954500, 1.926500),
    ('Kodak {Movie Stock}', 'Vision 500T [5263] [7263]'): (2.369500, 2.044500, 1.977500),
    ('Kodak {Movie Stock}', 'Vision 500T [5279] [7279]'): (1.886500, 1.658500, 1.658500),
    ('Kodak {Movie Stock}', 'Vision 800T [5289] [7289]'): (1.917000, 1.635000, 1.627000),
    ('Kodak {Movie Stock}', 'Vision Expr. 500T [5284] [7284]'): (2.170000, 1.888000, 1.901000),
    ('Kodak {Movie Stock}', 'Vision2 100T [5212] [7212]'): (1.986500, 1.728500, 1.641500),
    ('Kodak {Movie Stock}', 'Vision2 200T [5217] [7217]'): (1.955500, 1.729500, 1.635500),
    ('Kodak {Movie Stock}', 'Vision2 250D [5205] [7205]'): (1.961500, 1.739500, 1.642500),
    ('Kodak {Movie Stock}', 'Vision2 500T [5218] [7218]'): (2.017000, 1.798000, 1.835000),
    ('Kodak {Movie Stock}', 'Vision2 500T [5260]'): (2.015000, 1.733000, 1.739000),
    ('Kodak {Movie Stock}', 'Vision2 50D [5201] [7201]'): (1.992500, 1.752500, 1.619500),
    ('Kodak {Movie Stock}', 'Vision2 Expr. 500T [5229] [7229]'): (2.180000, 1.949000, 1.874000),
    ('Kodak {Movie Stock}', 'Vision3 200T [5213] [7213]'): (2.096000, 1.796000, 1.874000),
    ('Kodak {Movie Stock}', 'Vision3 250D [5207] [7207]'): (2.110500, 1.807500, 1.862500),
    ('Kodak {Movie Stock}', 'Vision3 500T [5219] [7219]'): (2.110500, 1.795500, 1.836500),
    ('Kodak {Movie Stock}', 'Vision3 50D [5203] [7203]'): (2.054500, 1.717500, 1.798500),
    ('Konica', 'Centuria 100'): (1.592000, 1.499000, 1.255000),
    ('Konica', 'Centuria 200'): (1.508000, 1.555000, 1.317000),
    ('Konica', 'Centuria 400'): (1.603000, 1.548000, 1.301000),
    ('Konica', 'Centuria 800'): (1.513000, 1.552000, 1.312000),
    ('Konica', 'Centuria APS 200'): (1.680000, 1.620000, 1.380000),
    ('Konica', 'Centuria APS 400'): (1.680000, 1.610000, 1.370000),
    ('Konica', 'Centuria APS 800'): (1.560000, 1.600000, 1.340000),
    ('Konica', 'Centuria PRO 400'): (1.800000, 1.720000, 1.550000),
    ('Konica', 'Centuria Portrait 400'): (1.720000, 1.782000, 1.530000),
    ('Konica', 'Centuria Super  100'): (1.640000, 1.590000, 1.310000),
    ('Konica', 'Centuria Super  200'): (1.630000, 1.570000, 1.350000),
    ('Konica', 'Centuria Super  400'): (1.530000, 1.610000, 1.390000),
    ('Konica', 'Centuria Super  800'): (1.560000, 1.600000, 1.390000),
    ('Konica', 'Centuria Super 1600'): (1.480000, 1.520000, 1.310000),
    ('Konica', 'Color JX 200'): (1.620000, 1.556000, 1.307000),
    ('Konica', 'Color JX 400'): (1.605000, 1.550000, 1.326000),
    ('Konica', 'Color JX-200M'): (1.826000, 1.826000, 1.383000),
    ('Konica', 'Color SR-G 3200'): (1.491000, 1.563000, 1.349000),
    ('Konica', 'Impresa 50 Professional'): (1.960000, 1.680000, 1.380000),
    ('Konica', 'Professional 160'): (2.180000, 1.720000, 1.680000),
    ('Konica', 'Professional 160PL'): (1.957000, 1.779000, 1.468000),
    ('Konica', 'Professional 160PS'): (1.979000, 1.829000, 1.479000),
    ('Konica', 'VX 100'): (1.618000, 1.460000, 1.223000),
    ('Konica', 'VX 100 Improved'): (1.700000, 1.560000, 1.340000),
    ('Konica', 'VX 200'): (1.800000, 1.590000, 1.350000),
    ('Konica', 'VX 400'): (1.660000, 1.680000, 1.340000),
    ('Konica', 'VX Super 100'): (1.620000, 1.570000, 1.340000),
    ('Konica', 'VX Super 200'): (1.620000, 1.540000, 1.320000),
    ('Konica', 'VX Super 400'): (1.710000, 1.670000, 1.480000),
    ('Rollei', 'Digibase CN 200 Pro'): (1.182000, 1.231000, 0.974000),
    ('Rollei', 'Digibase CN 200 Pro {4 min.}'): (1.177000, 1.225000, 0.960000),
    ('Rollei', 'RCN 640'): (1.881000, 1.778000, 1.637000),
    ('Rollei', 'RCN 640 {4 min.}'): (1.880000, 1.800000, 1.658000),
    ('Rollei', 'Scanfilm CN 400 Pro'): (1.298500, 1.306500, 1.006500),
}

# ---------------------------------------------------------------------------
# Constants from the binary
# ---------------------------------------------------------------------------
NBINS       = 0x8000                    # 32768 histogram bins (Photoshop 16-bit codes 0..32767)
P_BLACK     = 0.001                     # g2+0x540  "Black" percentile  (white anchor; plugin default 0.005, here 0.1 %)
GRAIN_BLOCK = 5                         # own addition: block size of the low-grain anchors (option, default off)
P_BPOINT    = 0.001                     # g2+0x628  "BPoint" percentile (black anchor; plugin default 0.005, here 0.1 %)
FLOOR       = 3.204345703125e-05        # 1.05 / 32768, lower limit in 0x1000aa20


# ---------------------------------------------------------------------------
# Gamma curves (0x10003c20 = decode, 0x10003a50 = encode)
# ---------------------------------------------------------------------------
# Films with a characteristic-curve file in the folder 'curves' (own addition, see build_luts / curve_correction)
FILM_CURVES = {
    ('Kodak', 'Portra 400 (2026)'): 'kodak_portra_400.txt',
    # The X5 presets share the datasheet curve: the toe/shoulder term is scaled to each preset's gammas (see
    # curve_correction), and the toe of Portra 400 is nearly neutral (recherche/negicc, 2026-09-18).
    ('Kodak', 'Portra 400 (X5 fit)'): 'kodak_portra_400.txt',
    ('Kodak', 'Portra 400 (X5 neutral)'): 'kodak_portra_400.txt',
    ('Kodak', 'Portra 400 (X5 balance)'): 'kodak_portra_400.txt',
}

_ICC_CACHE = {}
_CURVE_CACHE = {}


class ConversionError(ValueError):
    """Error with a message for the user (bad input, unsupported file, invalid region). The CLI prints it and
    exits; the GUI shows it in a dialog. Never SystemExit inside library code: worker threads would swallow it."""


def load_icc_trc(path):
    """Reads the rTRC/gTRC/bTRC tables (device value -> linear) from an ICC profile (v2 'curv')."""
    import os
    import struct
    path = resolve_icc(path)
    if path in _ICC_CACHE:
        return _ICC_CACHE[path]
    d = open(path, "rb").read()
    n = struct.unpack(">I", d[128:132])[0]
    tags = {}
    for i in range(n):
        sig, off, size = struct.unpack(">4sII", d[132 + 12 * i:144 + 12 * i])
        tags[sig] = (off, size)
    missing = [sig.decode() for sig in (b"rTRC", b"gTRC", b"bTRC") if sig not in tags]
    if missing:
        raise ConversionError(f"{os.path.basename(path)}: no RGB tone curves ({', '.join(missing)} missing); "
                              "grayscale or LUT-based profiles are not supported")
    curves = []
    fine = np.linspace(0, 1, 8193)                       # dense sampling for analytic curves (interp error < 1/32768)
    for sig in (b"rTRC", b"gTRC", b"bTRC"):
        off, size = tags[sig]
        typ = d[off:off + 4]
        if typ == b"curv":
            cnt = struct.unpack(">I", d[off + 8:off + 12])[0]
            if cnt == 0:
                xs, ys = np.array([0.0, 1.0]), np.array([0.0, 1.0])
            elif cnt == 1:
                gam = struct.unpack(">H", d[off + 12:off + 14])[0] / 256.0
                xs = fine; ys = xs ** gam
            else:
                ys = np.array(struct.unpack(">%dH" % cnt, d[off + 12:off + 12 + 2 * cnt])) / 65535.0
                xs = np.linspace(0, 1, cnt)
        elif typ == b"para":
            ft = struct.unpack(">H", d[off + 8:off + 10])[0]
            if ft not in (0, 1, 2, 3, 4):
                raise ConversionError(f"{os.path.basename(path)}: unknown parametric curve type {ft}")
            npar = {0: 1, 1: 3, 2: 4, 3: 5, 4: 7}[ft]
            pr = [v / 65536.0 for v in struct.unpack(">%di" % npar, d[off + 12:off + 12 + 4 * npar])]
            g = pr[0]; a, b, c, dd, e, f = (pr + [0] * 7)[1:7]
            xs = fine
            if ft in (1, 2) and a == 0:
                raise ConversionError(f"{os.path.basename(path)}: degenerate parametric curve (a = 0)")
            if ft == 0:
                ys = xs ** g
            elif ft == 1:
                ys = np.where(xs >= -b / a, np.clip(a * xs + b, 0, None) ** g, 0.0)
            elif ft == 2:
                ys = np.where(xs >= -b / a, np.clip(a * xs + b, 0, None) ** g + c, c)
            elif ft == 3:
                ys = np.where(xs >= dd, np.clip(a * xs + b, 0, None) ** g, c * xs)
            else:
                ys = np.where(xs >= dd, np.clip(a * xs + b, 0, None) ** g + e, c * xs + f)
        else:
            raise ConversionError(f"{os.path.basename(path)}: {sig.decode()} has type {typ!r}, only 'curv'/'para' are supported")
        curves.append((xs, ys))
    _ICC_CACHE[path] = curves
    return curves


def icc_info(path):
    """Short info on an ICC profile: description, device class, curve description (for the GUI)."""
    import struct
    path = resolve_icc(path)
    d = open(path, "rb").read()
    n = struct.unpack(">I", d[128:132])[0]
    tags = {}
    for i in range(n):
        sig, off, size = struct.unpack(">4sII", d[132 + 12 * i:144 + 12 * i])
        tags[sig] = (off, size)
    desc = ""
    if b"desc" in tags:
        off, size = tags[b"desc"]
        typ = d[off:off + 4]
        if typ == b"desc":
            cnt = struct.unpack(">I", d[off + 8:off + 12])[0]
            desc = d[off + 12:off + 12 + max(cnt - 1, 0)].decode("latin-1", "replace")
        elif typ == b"mluc":
            ln, ofs = struct.unpack(">II", d[off + 20:off + 28])
            desc = d[off + ofs:off + ofs + ln].decode("utf-16-be", "replace")
    curve = "?"
    try:
        xs, ys = load_icc_trc(path)[1]
        m = (xs > 0.05) & (xs < 0.95) & (ys > 0)
        g = np.polyfit(np.log(xs[m]), np.log(ys[m]), 1)[0]
        if np.allclose(ys[m], xs[m] ** g, atol=2e-3):
            curve = f"Gamma {g:.2f}"
        elif np.allclose(ys[m], decode_curve(xs[m], "srgb"), atol=2e-3):
            curve = "sRGB curve"
        elif np.allclose(ys[m], decode_curve(xs[m], "lstar"), atol=2e-3):
            curve = "L* curve"
        else:
            curve = f"Table, roughly Gamma {g:.2f}"
    except Exception as e:
        curve = f"Curve not readable ({e})"
    return dict(desc=desc.strip("\x00 "), cls=d[12:16].decode("latin-1"), curve=curve,
                matrix=all(t in tags for t in (b"rXYZ", b"gXYZ", b"bXYZ")))


def decode_curve(x, curve, channel=None):
    """Input GammaC: encoded -> linear. x in 0..1.
    curve: 'linear', 'srgb', 'lstar', number (gamma) or 'icc:<file>' (TRC tables of the scanner profile, per channel)."""
    x = np.asarray(x, dtype=np.float64)
    if curve == "linear":
        return x
    if str(curve).startswith("icc:"):
        curves = load_icc_trc(curve[4:])
        if channel is None:
            channel = 1
        xs, ys = curves[channel]
        return np.interp(x, xs, ys)
    if curve == "srgb":
        return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    if curve == "lstar":
        L = x * 100.0
        return np.where(L > 8.0, ((L + 16.0) / 116.0) ** 3, L / 903.3)
    g = float(curve)
    return x ** g


def encode_curve(x, curve, channel=None):
    """Output GammaC: linear -> encoded. x in 0..1.
    curve: 'linear', 'srgb', 'lstar', number (gamma) or 'icc:<file>' (TRC of the output profile inverted, per channel)."""
    x = np.asarray(x, dtype=np.float64)
    if curve == "linear":
        return x
    if str(curve).startswith("icc:"):
        curves = load_icc_trc(curve[4:])
        xs, ys = curves[1 if channel is None else channel]
        return np.interp(x, ys, xs)          # inverse of the TRC (monotonically increasing)
    if curve == "srgb":
        return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)
    if curve == "lstar":
        y = np.where(x > 216.0 / 24389.0, 116.0 * np.cbrt(x) - 16.0, x * 903.3)
        return y / 100.0
    g = float(curve)
    return x ** (1.0 / g)


# ---------------------------------------------------------------------------
# Percentile searches, 1:1 after 0x10002c30 and 0x10002a00
# ---------------------------------------------------------------------------
def low_percentile(hist, total, frac, lin):
    """0x10002c30: smallest bin b >= 1 whose sum hist[1..b] >= frac*total -> lin[b]."""
    target = frac * total
    if target < 1.0:            # plugin: 'comisd 1.0, target; jbe' -> target = -1.0 -> lin[1] (= black image).
        target = 1.0            # here: skip nothing, take the first occupied bin (percentile 0 behaves sanely)
    cum = 0.0
    for b in range(1, NBINS):
        cum += hist[b]
        if target <= cum:
            return lin[b]
    return lin[NBINS - 1]


def high_percentile(hist, total, frac, lin):
    """0x10002a00: largest bin b whose sum hist[b..32767] >= frac*total -> lin[b]."""
    target = frac * total
    if target < 1.0:
        target = 1.0            # see low_percentile (plugin returned lin[NBINS] = 1.0 here)
    cum = 0.0
    for b in range(NBINS - 1, 0, -1):
        cum += hist[b]
        if target <= cum:
            return lin[b]
    return lin[1]


# ---------------------------------------------------------------------------
# Core: LUT construction (0x100182e0, branch mode == 1)
# ---------------------------------------------------------------------------
def build_luts(hists, total, gammas, in_curve="linear", p_black=P_BLACK, p_bpoint=P_BPOINT, verbose=True, warn=None,
               curve=None):
    """
    hists : 3 x 32768 channel histograms of the Photoshop codes, total: pixel count
    gammas: (gR, gG, gB)
    curve : None (plugin model) or a curve dict from load_film_curve: datasheet toe/shoulder on top of the gammas
    returns luts (3 x 32769), bpoint, bpcolor (3,), plus lo/hi/v per channel
    """
    # lin[i] = decode(i/32768), i = 0..32768 (0x10003fc0 fills 0..32767; index 32768 is added as 1.0)
    codes01 = np.arange(NBINS + 1, dtype=np.float64) / 32768.0
    lins = [decode_curve(codes01, in_curve, c) for c in range(3)]      # with icc: per-channel tables

    # Validity check as in 0x100182e0: gamma outside 0.1..10 -> all three = 1.0
    g = np.array(gammas, dtype=np.float64)
    if np.any(np.abs(g) < 0.1) or np.any(np.abs(g) > 10.0):
        (warn or (lambda t: print(t, file=sys.stderr)))("Warning: gamma outside 0.1..10, plugin sets all three gammas to 1.0")
        g[:] = 1.0

    luts = np.empty((3, NBINS + 1), dtype=np.float64)
    lo = np.empty(3); hi = np.empty(3); k = np.empty(3); v = np.empty(3)
    for c in range(3):
        lin = lins[c]
        hist = hists[c]
        lo[c] = low_percentile(hist, total, p_black, lin)       # lowest scanner value = densest point of the negative -> white
        k[c]  = lo[c] ** g[c]                                    # g2+0x648..
        hi[c] = high_percentile(hist, total, p_bpoint, lin)     # highest scanner value = thinnest point (film base) -> black
        v[c]  = k[c] * hi[c] ** (-g[c])                          # = (lo/hi)^g
        with np.errstate(divide="ignore"):
            luts[c, 1:] = k[c] * lin[1:] ** (-g[c])              # (lo / lin[i])^g for i = 1..32768
        luts[c, 0] = luts[c, 1]                                  # LUT[0] = LUT[1]

    # Own addition: datasheet toe/shoulder, exactly 0 at both anchors. All channels or none, never a colour shift.
    use_curve = curve is not None and lo.min() > 0 and hi.min() > 0
    if use_curve:
        # Datasheet gammas (gamma * slope = 1 in every channel): each channel gets its own datasheet toe/shoulder.
        # Scanner-fitted gammas: the per-channel Status-M shapes do not transfer, and the toe of the film is nearly
        # neutral for an RGB scanner (recherche/negicc), so the green curve is used for all three channels, placed
        # on each channel's own density scale -> the term is a pure function of exposure, no colour shift.
        neutral = bool(np.any(np.abs(g * curve["slope"] - 1.0) >= 0.02))
        for c in range(3):
            with np.errstate(divide="ignore"):
                dens = -np.log10(lins[c][1:])
            term = curve_correction(curve, c, dens, -np.log10(hi[c]), -np.log10(lo[c]), g[c], neutral)
            luts[c, 1:] *= 10.0 ** term
            luts[c, 0] = luts[c, 1]

    bpoint  = float(v.min())                                     # g2+0xb0
    bpcolor = v - bpoint                                         # g2+0xe8.. (BP Color)

    if verbose:
        for c, n in enumerate("RGB"):
            print(f"  {n}: gamma={g[c]:.4f}  lo={lo[c]:.6f}  hi={hi[c]:.6f}  k=lo^g={k[c]:.6f}  v=(lo/hi)^g={v[c]:.6f}")
        print(f"  BPoint={bpoint:.6f}  BPColor={bpcolor.round(6).tolist()}")
    return luts, bpoint, bpcolor, dict(lo=lo, hi=hi, k=k, v=v, gammas=g, curve=use_curve)


# ---------------------------------------------------------------------------
# Pixel pipeline (0x1000aa20), reduced to the conversion
# ---------------------------------------------------------------------------
def apply(codes, luts, bpoint, bpcolor, black=0.0, cc=(1.0, 1.0, 1.0), use_bpoint=True):
    out = np.empty(codes.shape, dtype=np.float64)
    for c in range(3):
        p = luts[c][codes[..., c]]
        if use_bpoint:
            p = p - bpoint - bpcolor[c]
        p = p * (2.0 ** (-black)) * cc[c]
        out[..., c] = p
    out[out <= FLOOR] = FLOOR
    return out


# ---------------------------------------------------------------------------
# Input/output
# ---------------------------------------------------------------------------
def to_codes(img):
    """File values -> Photoshop codes 0..32767 (0x10011e40)."""
    if img.ndim == 2:
        img = np.stack([img, img, img], axis=-1)
    if img.ndim != 3 or img.shape[-1] == 2 or img.shape[-1] > 4:
        raise ConversionError(f"unsupported image layout {img.shape}: need RGB, RGBA or grayscale")
    img = img[..., :3]
    if img.dtype.kind == "u" and img.dtype.itemsize == 1:
        codes = img.astype(np.int32) << 7                      # 8 bit: value * 128
    elif img.dtype.kind == "u" and img.dtype.itemsize == 2:    # also big-endian (Imacon 3f/fff)
        codes = np.rint(img.astype(np.float64) * 32768.0 / 65535.0).astype(np.int32)   # Photoshop: 65535 -> 32768
    else:
        raise ConversionError(f"only 8- or 16-bit integer images are supported (this file: {img.dtype})")
    return np.clip(codes, 0, NBINS - 1).astype(np.uint16)


def to_file(lin_out, out_curve, bits=16):
    lin_out = np.clip(lin_out, 0.0, 1.0)                        # clip values > 1 (High Stops = 0)
    if str(out_curve).startswith("icc:"):
        enc = np.empty_like(lin_out)
        for c in range(3):
            enc[..., c] = encode_curve(lin_out[..., c], out_curve, c)
    else:
        enc = encode_curve(lin_out, out_curve)
    codes = np.floor(enc * 32768.0)                              # cvttsd2si: truncate
    if bits == 16:
        return np.clip(np.rint(codes * 65535.0 / 32768.0), 0, 65535).astype(np.uint16)
    return np.clip(codes / 128.0, 0, 255).astype(np.uint8)


def read_image(path):
    """TIFF/3f/fff: first page as memmap (no loading into memory); other formats via PIL if available.
    Planar-separate TIFFs (3 x H x W) are returned interleaved (H x W x 3)."""
    img = None
    try:
        import tifffile
        try:
            img = tifffile.TiffFile(path).pages[0].asarray(out="memmap")
        except Exception:
            try:
                img = tifffile.imread(path)
            except Exception:
                img = None
    except ImportError:
        pass
    if img is None:
        try:
            from PIL import Image
            img = np.asarray(Image.open(path))
        except ImportError:
            raise ConversionError(f"cannot read {os.path.basename(path)} (not a readable TIFF/3f/fff, and PIL is not installed)")
        except Exception as e:
            raise ConversionError(f"cannot read {os.path.basename(path)}: {e}")
    if img.ndim == 3 and img.shape[0] in (3, 4) and img.shape[-1] not in (1, 3, 4):
        img = np.moveaxis(img, 0, -1)                    # planar (samples first) -> interleaved
    return img


def scan_input_profile(path):
    """Imacon/Hasselblad 3f/fff: name (and Mac path) of the FlexColor input profile from the embedded
    setup plist (private TIFF tag 50457). Returns (name, path) or (None, None) for other files."""
    import re, html
    try:
        import tifffile
        with tifffile.TiffFile(path) as t:
            tag = t.pages[0].tags.get(50457)
            if tag is None:
                return None, None
            d = bytes(tag.value)
    except Exception:
        return None, None
    m = re.search(rb"<key>InputProfile</key>(.{0,600}?)</dict>", d, re.S)
    if not m:
        return None, None
    blk = m.group(1)
    name = re.search(rb"<key>Name</key>\s*<string>([^<]*)</string>", blk)
    pth = re.search(rb"<key>Path</key>\s*<string>([^<]*)</string>", blk)
    dec = lambda x: html.unescape(x.group(1).decode("utf-8", "replace")) if x else None
    return dec(name), dec(pth)


def find_icc_by_name(name, dirs):
    """Looks for <name>.icc / .icm (case-insensitive) in the given folders."""
    import os
    if not name:
        return None
    want = name.strip().lower()
    for d in dirs:
        try:
            for f in os.listdir(d):
                base, ext = os.path.splitext(f)
                if ext.lower() in (".icc", ".icm") and base.strip().lower() == want:
                    return os.path.join(d, f)
        except OSError:
            pass
    return None


def find_film_key(name):
    """(manufacturer, film) key of FILMS for 'Manufacturer/Film' or a unique film name."""
    if "/" in name:
        maker, film = name.split("/", 1)
        key = (maker.strip(), film.strip())
        if key in FILMS:
            return key
    hits = [k for k in FILMS if k[1].lower() == name.strip().lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ConversionError("ambiguous, please specify manufacturer/film: " + ", ".join(f"{m}/{f}" for m, f in hits))
    hits = [k for k in FILMS if name.strip().lower() in k[1].lower()]
    raise ConversionError("Film not found. Similar: " + ", ".join(f"{m}/{f}" for m, f in hits[:15]))


def find_film(name):
    return FILMS[find_film_key(name)]


def film_curve_path(name):
    """Path of the characteristic-curve file for a film ('Manufacturer/Film'), None if the film has none."""
    try:
        fn = FILM_CURVES.get(find_film_key(name))
    except ConversionError:
        return None
    p = os.path.join(curves_dir(), fn) if fn else None
    return p if p and os.path.isfile(p) else None


def load_film_curve(path):
    """Characteristic curves from a text file: columns logH, D_R, D_G, D_B (density rising with exposure),
    header line '# straight: <logH0> <logH1>' = range of the straight-line fit. Returns a dict with
    logH (n,), D (3, n), slope/intercept (3,) of the straight part, anchor (3,): density where the toe reaches half
    the straight slope (the black anchor of a scan is placed there), dmax (3,): last density of the table."""
    path = os.path.abspath(path)
    if path in _CURVE_CACHE:
        return _CURVE_CACHE[path]
    straight = None
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                t = line.strip()
                if t.startswith("#"):
                    m = re.match(r"#\s*straight:\s*([-+.\d]+)\s+([-+.\d]+)", t)
                    if m:
                        straight = (float(m.group(1)), float(m.group(2)))
                    continue
                if t:
                    rows.append([float(x) for x in t.replace(",", " ").split()])
        tab = np.array(rows, dtype=np.float64)
    except (OSError, ValueError) as e:
        raise ConversionError(f"curve file {os.path.basename(path)} unreadable: {e}")
    if tab.ndim != 2 or tab.shape[1] != 4 or tab.shape[0] < 6 or straight is None:
        raise ConversionError(f"curve file {os.path.basename(path)}: need columns logH D_R D_G D_B and a '# straight:' line")
    order = np.argsort(tab[:, 0])
    logH, D = tab[order, 0], tab[order, 1:].T
    if np.any(np.diff(logH) <= 0) or np.any(np.diff(D, axis=1) <= 0):
        raise ConversionError(f"curve file {os.path.basename(path)}: logH and densities must rise strictly")
    m = (logH >= straight[0]) & (logH <= straight[1])
    if m.sum() < 3:
        raise ConversionError(f"curve file {os.path.basename(path)}: straight range contains fewer than 3 points")
    slope = np.empty(3); intercept = np.empty(3); anchor = np.empty(3)
    for c in range(3):
        slope[c], intercept[c] = np.polyfit(logH[m], D[c][m], 1)
        if slope[c] <= 0:
            raise ConversionError(f"curve file {os.path.basename(path)}: straight part of channel {'RGB'[c]} has no positive slope")
        local = np.gradient(D[c], logH)
        if not np.any(local >= slope[c] / 2):
            raise ConversionError(f"curve file {os.path.basename(path)}: channel {'RGB'[c]} never reaches half its straight slope")
        i = int(np.argmax(local >= slope[c] / 2))                # first point (from low exposure) at half the straight slope
        anchor[c] = D[c][0] if i == 0 else np.interp(slope[c] / 2, local[i - 1:i + 1], D[c][i - 1:i + 1])
    cv = dict(path=path, logH=logH, D=D, slope=slope, intercept=intercept, anchor=anchor, dmax=D[:, -1].copy(),
              straight=straight)
    _CURVE_CACHE[path] = cv
    return cv


def curve_correction(cv, c, dens, d_hi, d_lo, gamma=None, neutral=False):
    """Toe/shoulder term of the datasheet curve for channel c, in log10 exposure, for scanner densities dens
    (array, D = -log10 of the linearized scanner value). d_hi = density of the black anchor (thinnest point),
    d_lo = density of the white anchor (densest point). The scan is placed on the datasheet axis so that the black
    anchor sits at cv['anchor'][c] (half-slope point of the toe). Scanner density differences are converted to
    datasheet (Status M) density with the factor gamma * datasheet slope: the preset gamma says how much log
    exposure a scanner density step is worth, the datasheet slope how much Status-M density that exposure makes.
    With gamma = 1/slope (the datasheet preset) the factor is 1, i.e. densities are taken 1:1 as before; a
    scanner-fitted gamma (e.g. blue 1.95 instead of 1.57) moves the toe to where that scanner actually sees it.
    The term is the deviation of the curve's inverse from its straight line, minus the straight line through its
    values at the two anchors, so it is exactly 0 at both anchors and 0 outside of them: white and black stay where
    the plain model puts them. Returned in log10 units, i.e. pos *= 10**term.
    neutral = use the green channel's curve for every channel (toe/shoulder as a function of exposure only, the
    same for R, G and B); requires gamma. Used for scanner-fitted gammas, see build_luts."""
    cc = 1 if neutral else c
    logH, D = cv["logH"], cv["D"][cc]
    s, b, da, dmax = cv["slope"][cc], cv["intercept"][cc], cv["anchor"][cc], cv["dmax"][cc]
    span = d_lo - d_hi
    if not (span > 1e-6):
        return np.zeros_like(dens)
    kd = 1.0 if gamma is None else float(gamma) * s          # scanner density -> datasheet density of that curve
    if not neutral and abs(kd - 1.0) < 0.02:
        kd = 1.0                                               # datasheet preset: keep the 1:1 placement exactly
    def delta(dq):                                             # inverse curve minus its straight line
        dq = np.clip(dq, da, dmax)
        return np.interp(dq, D, logH) - (dq - b) / s
    dsm = (dens - d_hi) * kd + da                              # scan density -> datasheet density
    t = np.clip((dens - d_hi) / span, 0.0, 1.0)
    d0 = delta(np.array([da]))[0]
    d1 = delta(np.array([span * kd + da]))[0]
    term = delta(dsm) - d0 - (d1 - d0) * t
    term[(dens < d_hi) | (dens > d_lo)] = 0.0
    return term


def resource_dir():
    """Program folder: next to the script, in the EXE the PyInstaller directory."""
    import os
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def version():
    """Version string: the file VERSION next to the program (written by the release build), otherwise 'dev'."""
    try:
        with open(os.path.join(resource_dir(), "VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "dev"
    except OSError:
        return "dev"


def profiles_dir():
    """Folder 'profiles' with the bundled ICC profiles (scanner profiles and working color spaces)."""
    import os
    return os.path.join(resource_dir(), "profiles")


def curves_dir():
    """Folder 'curves' with the bundled characteristic-curve files (see FILM_CURVES)."""
    import os
    return os.path.join(resource_dir(), "curves")


def resolve_icc(path):
    """Resolve an ICC path: as given, otherwise in the folder 'profiles' (also without the .icc/.icm extension)."""
    import os
    if os.path.exists(path):
        return path
    base = os.path.basename(path)
    cands = [os.path.join(profiles_dir(), base)]
    if not base.lower().endswith((".icc", ".icm")):
        cands += [os.path.join(profiles_dir(), base + ext) for ext in (".icc", ".icm")]
    for c in cands:
        if os.path.exists(c):
            return c
    return path


def resolve_gammas(film=None, gammas=None, log=print):
    if gammas:
        g = tuple(gammas)
    elif film:
        g = find_film(film)
    else:
        g = (1.0, 1.0, 1.0)          # "B&W Start"
        log("no film specified, using B&W Start (1, 1, 1)")
    return tuple(g)


def film_short_name(film):
    """Short film name for file names: without manufacturer, plugin codes in [] dropped, spaces removed,
    groups in () or {} appended with '-': 'Kodak/Portra 400 (2026)' -> 'Portra400-2026',
    'Kodak/Portra 400 [4056] [5056] [6056]' -> 'Portra400', 'Kodak/Portra 800 {2008 Push 1}' -> 'Portra800-2008-Push1'."""
    name = film.split("/", 1)[-1]
    name = re.sub(r"\[[^\]]*\]", "", name)
    groups = re.findall(r"[({]([^)}]*)[)}]", name)
    base = re.sub(r"[^A-Za-z0-9]+", "", re.sub(r"[({][^)}]*[)}]", "", name))
    parts = [base] if base else []
    for g in groups:
        g = re.sub(r"(?<=[A-Za-z])\s+(?=\d)", "", g)          # 'Push 1' -> 'Push1'
        g = re.sub(r"[^A-Za-z0-9]+", "-", g).strip("-")
        if g:
            parts.append(g)
    return "-".join(parts) or "film"


def grain_block(n):
    """Block size of the low-grain anchors: 0/1/None/False = off (1), True = GRAIN_BLOCK, even sizes are raised to the
    next odd one (2x2 pixel pattern of Flextight scans, see the subsample step)."""
    n = GRAIN_BLOCK if n is True else int(n or 1)
    if n < 1:
        raise ConversionError("grain block size must be 1 (off) or larger")
    return n + 1 if n > 1 and n % 2 == 0 else n


def block_mean_codes(img, block, step=None, chunk_rows=64):
    """Codes (see to_codes) of the block x block mean values of img, one block every `step` pixels (default: block =
    non-overlapping). Own addition for the low-grain anchors: the 0.1 % percentiles of single pixels are grain
    outliers, mostly in the blue channel (densest layer), which makes the white anchor too dense there and the
    positive yellow; the mean of a small block keeps the image detail but not the grain. The mean is taken on the
    file values, the difference to a mean in linear light is negligible at grain amplitude."""
    step = step or block
    if step < block:
        raise ConversionError("block_mean_codes: step must not be smaller than the block")
    if img.ndim == 2:
        img = img[..., None]
    h = (img.shape[0] - block) // step + 1
    w = (img.shape[1] - block) // step + 1
    if h < 1 or w < 1:
        return np.empty((0, 0, 3), dtype=np.uint16)
    parts = []
    for r0 in range(0, h, chunk_rows):
        r1 = min(h, r0 + chunk_rows)
        a = np.asarray(img[r0 * step:(r1 - 1) * step + block, :(w - 1) * step + block, :3])
        acc = np.zeros((r1 - r0, w, a.shape[2]), dtype=np.float64)
        for dy in range(block):
            for dx in range(block):
                acc += a[dy::step, dx::step][:r1 - r0, :w]
        m = acc / (block * block)
        if m.shape[2] == 1:
            m = m[..., 0]                            # grayscale: to_codes stacks it to three channels
        parts.append(to_codes(np.rint(m).astype(img.dtype.newbyteorder("=") if img.dtype.kind == "u" else np.uint16)))
    return np.concatenate(parts, axis=0)


def settings_name(film=None, gammas=None, film_curve=False, black=0.0, p_black=P_BLACK, p_bpoint=P_BPOINT, grain=1):
    """Conversion settings as file-name tokens, e.g. 'Portra400-2026_toe_ev-05_w01_b05': film short name
    (or 'g<R>-<G>-<B>' without a film), 'toe' with the datasheet curve, 'ev<+-x>' for an exposure other than 0
    (exposure = -black), white and black percentile in percent, 'lg<n>' with low-grain anchors (block size n). Numbers are written without the decimal point
    (0.1 -> 01, 0.5 -> 05, 1 -> 1, 1.84 -> 184) so that the name contains no dot besides the extension.
    Only letters, digits, '+', '-' and '_'."""
    def num(x, fmt="g"):
        return format(x, fmt).replace(".", "")
    tokens = [film_short_name(film) if film else "g" + "-".join(num(g, ".2f") for g in (gammas or (1, 1, 1)))]
    if film_curve:
        tokens.append("toe")
    exposure = round(-float(black), 4) + 0.0
    if exposure != 0:
        tokens.append("ev" + num(exposure, "+g"))
    tokens.append("w" + num(round(p_black * 100, 4)))
    tokens.append("b" + num(round(p_bpoint * 100, 4)))
    if grain_block(grain) > 1:
        tokens.append(f"lg{grain_block(grain)}")
    return "_".join(tokens)


def settings_description(film=None, gammas=None, film_curve=False, black=0.0, p_black=P_BLACK, p_bpoint=P_BPOINT,
                         in_curve="linear", out_curve="2.2", stats_crop=None, grain=1):
    """One-line summary of the conversion settings, stored in the TIFF's ImageDescription tag (7-bit ASCII)."""
    parts = [f"BallastConverter {version()}"]
    if film:
        parts.append(f"film={film}")
    if gammas:
        parts.append("gammas=" + " ".join(f"{g:.3f}" for g in gammas))
    parts.append("datasheet_curve=" + ("on" if film_curve else "off"))
    parts.append(f"exposure={round(-float(black), 4) + 0.0:+g}")
    parts.append(f"white={round(p_black * 100, 4):g}%")
    parts.append(f"black={round(p_bpoint * 100, 4):g}%")
    if grain_block(grain) > 1:
        parts.append(f"low_grain_anchors={grain_block(grain)}x{grain_block(grain)}")
    parts.append(f"in_curve={in_curve}")
    parts.append(f"out_curve={out_curve}")
    if stats_crop:
        parts.append("stats_crop=" + " ".join(str(int(v)) for v in stats_crop))
    return "; ".join(parts).encode("ascii", "replace").decode("ascii")


def convert(input_path, output_path, gammas, in_curve="linear", out_curve="2.2",
            p_black=P_BLACK, p_bpoint=P_BPOINT, black=0.0, cc=(1.0, 1.0, 1.0), use_bpoint=True,
            bits=16, crop=None, stats_crop=None, embed_icc="auto", subsample=1,
            log=print, progress=None, cancel=None, film_curve=None, film=None, grain=1):
    """
    Complete conversion negative -> positive, writes output_path.
    film_curve          : None, or path of a characteristic-curve file (see load_film_curve): datasheet toe/shoulder
    film                : film name, only for the settings summary in the TIFF's ImageDescription
    grain               : block size of the low-grain anchors (see block_mean_codes), 1 = off = percentiles of single
                          pixels as in the plugin. Only the two anchors change, the output pixels are not smoothed.
    log(text)           : messages
    progress(frac)      : 0..1 (histogram = first half, writing = second half)
    cancel()            : returns True if the conversion should be aborted
    subsample           : use only every n-th pixel (fast preview), crop values in original pixels
    returns dict with lo/hi/k/v/gammas/bpoint/bpcolor/clipped
    """
    import os
    import gc
    import tifffile
    if not os.path.isfile(input_path):
        raise ConversionError(f"input file not found: {input_path}")
    if os.path.exists(output_path) and os.path.samefile(input_path, output_path) or \
            os.path.normcase(os.path.abspath(input_path)) == os.path.normcase(os.path.abspath(output_path)):
        raise ConversionError("output file must not be the input file (the scan would be overwritten)")
    if not os.path.isdir(os.path.dirname(os.path.abspath(output_path))):
        raise ConversionError(f"output folder does not exist: {os.path.dirname(os.path.abspath(output_path))}")
    if not (0 < p_black <= 0.5 and 0 < p_bpoint <= 0.5):
        raise ConversionError("percentiles must be between 0 and 0.5 (0 %..50 %)")
    curve = load_film_curve(film_curve) if film_curve else None
    grain = grain_block(grain)
    img = read_image(input_path)
    if crop:
        x0, y0, x1, y1 = crop
        img = img[y0:y1, x0:x1]
    if subsample > 1 and subsample % 2 == 0:
        subsample += 1                         # odd step: samples both phases of a 2x2 pixel pattern equally
        log(f"subsample raised to {subsample} (even steps bias the percentiles on scans with a checkerboard pattern)")
    full = img                                  # low-grain anchors average neighbouring pixels of the unsampled image
    if subsample > 1:
        img = img[::subsample, ::subsample]
    H, W = img.shape[0], img.shape[1]
    log(f"Image {W}x{H}, gammas {tuple(round(g, 4) for g in gammas)}, input curve {in_curve}"
        + (f", datasheet curve {os.path.basename(curve['path'])}" if curve else "")
        + (f", low-grain anchors {grain}x{grain}" if grain > 1 else ""))
    stats_img = img
    if stats_crop:
        x0, y0, x1, y1 = stats_crop
        if crop:                                   # stats-crop refers to the original image
            x0 -= crop[0]; x1 -= crop[0]; y0 -= crop[1]; y1 -= crop[1]
        s = subsample
        up = lambda v: -(-max(v, 0) // s)       # start rounded up: never a row/column outside the region
        stats_img = img[up(y0):max(y1, 0) // s, up(x0):max(x1, 0) // s]
        if stats_img.size == 0:
            raise ConversionError("Statistics region lies outside the image")
    chunk = 256
    if grain > 1:
        region = full
        if stats_crop:                             # x0..y1 are relative to the cropped image by now
            region = full[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
        stats_img = block_mean_codes(region, grain, max(grain, subsample))
        if stats_img.size == 0:
            raise ConversionError("Statistics region is smaller than one block of the low-grain anchors")

    hists = np.zeros((3, NBINS), dtype=np.float64)
    total = 0
    n_stats = stats_img.shape[0]
    for y0 in range(0, n_stats, chunk):
        if cancel and cancel():
            return None
        codes = stats_img[y0:y0 + chunk] if grain > 1 else to_codes(np.asarray(stats_img[y0:y0 + chunk]))
        for c in range(3):
            hists[c] += np.bincount(codes[..., c].ravel(), minlength=NBINS)
        total += codes.shape[0] * codes.shape[1]
        if progress:
            progress(0.5 * min(y0 + chunk, n_stats) / n_stats)

    luts, bpoint, bpcolor, info = build_luts(hists, total, gammas, in_curve, p_black, p_bpoint, verbose=False, warn=log,
                                             curve=curve)
    for c, n in enumerate("RGB"):
        log(f"  {n}: gamma={info['gammas'][c]:.4f}  lo={info['lo'][c]:.6f}  hi={info['hi'][c]:.6f}  "
            f"k=lo^g={info['k'][c]:.6f}  v=(lo/hi)^g={info['v'][c]:.6f}")
    log(f"  BPoint={bpoint:.6f}  BPColor={bpcolor.round(6).tolist()}")

    extratags = []
    icc_path = embed_icc
    if icc_path == "auto":
        if str(out_curve).startswith("icc:"):
            icc_path = out_curve[4:]
        else:
            cand = os.path.join(profiles_dir(), "AdobeRGB1998.icc")
            icc_path = cand if (str(out_curve) == "2.2" and os.path.exists(cand)) else "none"
    if icc_path and icc_path != "none":
        icc_path = resolve_icc(icc_path)
        icc = open(icc_path, "rb").read()
        extratags.append((34675, 7, len(icc), icc, True))      # InterColorProfile
        log(f"  embedded profile: {icc_path}")

    description = settings_description(film, gammas, bool(film_curve), black, p_black, p_bpoint,
                                       in_curve, os.path.basename(str(out_curve)), stats_crop, grain)
    try:
        out = tifffile.memmap(output_path, shape=(H, W, 3), dtype=np.uint16 if bits == 16 else np.uint8,
                              photometric="rgb", description=description, extratags=extratags)
    except OSError as e:
        raise ConversionError(f"cannot write {output_path}: {e}")

    def discard():
        """Unmap and delete a partial output (also on Windows, where a mapped file cannot be removed)."""
        try:
            out.flush()
        except Exception:
            pass
        del_ok = False
        for _ in range(3):
            gc.collect()
            try:
                os.remove(output_path)
                del_ok = True
                break
            except OSError:
                pass
        return del_ok

    clipped = 0
    try:
        for y0 in range(0, H, chunk):
            if cancel and cancel():
                del out
                discard()
                return None
            codes = to_codes(np.asarray(img[y0:y0 + chunk]))
            lin_out = apply(codes, luts, bpoint, bpcolor, black, tuple(cc), use_bpoint)
            clipped += int((lin_out > 1.0).sum())
            out[y0:y0 + chunk] = to_file(lin_out, out_curve, bits)
            if progress:
                progress(0.5 + 0.5 * min(y0 + chunk, H) / H)
        out.flush()
        del out
    except BaseException:
        try:
            del out
        except NameError:
            pass
        discard()
        raise
    frac = clipped / (3.0 * H * W) * 100
    log(f"  share of clipped values: {frac:.3f} %")
    log(f"written: {output_path}")
    info.update(bpoint=bpoint, bpcolor=bpcolor, clipped_percent=frac, width=W, height=H)
    return info


def convert_codes(codes, gammas, in_curve="linear", out_curve="2.2", p_black=P_BLACK, p_bpoint=P_BPOINT,
                  black=0.0, cc=(1.0, 1.0, 1.0), use_bpoint=True, stats=None, bits=8, film_curve=None,
                  stats_codes=None):
    """Conversion of an already loaded image (codes 0..32767, HxWx3), for the preview in the GUI.
    stats: (y0, y1, x0, x1) region in pixels of this image for the percentiles, None = whole image.
    film_curve: None or path of a characteristic-curve file (datasheet toe/shoulder, see load_film_curve).
    stats_codes: None, or the codes to take the percentiles from instead (already cut to the region; low-grain
    anchors: block means from block_mean_codes), `stats` is ignored then.
    Returns (output image uint8/uint16, info)."""
    if stats_codes is None:
        stats_codes = codes if stats is None else codes[stats[0]:stats[1], stats[2]:stats[3]]
    if stats_codes.size == 0:
        raise ConversionError("Statistics region lies outside the image")
    if not (0 < p_black <= 0.5 and 0 < p_bpoint <= 0.5):
        raise ConversionError("percentiles must be between 0 and 0.5 (0 %..50 %)")
    hists = np.stack([np.bincount(stats_codes[..., c].ravel(), minlength=NBINS).astype(np.float64) for c in range(3)])
    total = stats_codes.shape[0] * stats_codes.shape[1]
    curve = load_film_curve(film_curve) if film_curve else None
    luts, bpoint, bpcolor, info = build_luts(hists, total, gammas, in_curve, p_black, p_bpoint, verbose=False, curve=curve)
    # The whole pipeline is pointwise per channel: compute once for all 32768 codes, then only look up.
    all_codes = np.repeat(np.arange(NBINS, dtype=np.uint16)[:, None], 3, axis=1)          # (NBINS, 3)
    lin_tab = apply(all_codes, luts, bpoint, bpcolor, black, tuple(cc), use_bpoint)
    out_tab = to_file(lin_tab, out_curve, bits)                                            # (NBINS, 3)
    out = np.empty(codes.shape, dtype=out_tab.dtype)
    clipped = 0
    for c in range(3):
        out[..., c] = out_tab[codes[..., c], c]
        clipped += int(np.bincount(codes[..., c].ravel(), minlength=NBINS)[lin_tab[:, c] > 1.0].sum())
    info.update(bpoint=bpoint, bpcolor=bpcolor, clipped_percent=clipped / (3.0 * codes.shape[0] * codes.shape[1]) * 100)
    return out, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="negative scan (16-bit linear TIFF recommended, as the plugin requires)")
    ap.add_argument("output", nargs="?", help="output file (TIFF)")
    ap.add_argument("--film", help='e.g. "Kodak/Portra 400NC" (see --list-films)')
    ap.add_argument("--gammas", nargs=3, type=float, metavar=("gR", "gG", "gB"), help="specify the film gammas directly")
    ap.add_argument("--in-curve", default="linear", help="input curve: linear (G/L=L, default), 2.2, 1.8, srgb, lstar or icc:<ScannerProfile.icc> (TRC tables, per channel; the file is also looked for in the folder profiles)")
    ap.add_argument("--out-curve", default="icc:AdobeRGB1998.icc", help="output curve: icc:<Profile.icc> (default profiles/AdobeRGB1998.icc; curve from the profile, profile is embedded), or 2.2, 1.8, srgb, lstar, linear")
    ap.add_argument("--p-black", type=float, default=P_BLACK, help="lower percentile, white anchor (default 0.001, plugin 0.005)")
    ap.add_argument("--p-bpoint", type=float, default=P_BPOINT, help="upper percentile, black anchor (default 0.001, plugin 0.005)")
    ap.add_argument("--black", type=float, default=0.0, help="Black in stops (factor 2^-Black), default 0")
    ap.add_argument("--cc", nargs=3, type=float, default=(1.0, 1.0, 1.0), metavar=("R", "G", "B"), help="CC multipliers, default 1 1 1")
    ap.add_argument("--no-bpoint", action="store_true", help="disable the black point subtraction")
    ap.add_argument("--bits", type=int, default=16, choices=(8, 16))
    ap.add_argument("--crop", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"), help="output only this region (pixels)")
    ap.add_argument("--stats-crop", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"), help="build histogram/percentiles only from this region (pixels of the original image, also together with --crop), output stays complete; excludes film rebate and perforation")
    ap.add_argument("--embed-icc", default="auto", help="embed ICC profile: path, 'none' or 'auto' (default: with --out-curve icc: that profile, with 2.2 profiles/AdobeRGB1998.icc)")
    ap.add_argument("--subsample", type=int, default=1, help="only every n-th pixel (fast preview)")
    ap.add_argument("--datasheet-curve", action="store_true", help="apply the toe/shoulder of the film's datasheet characteristic curve on top of the gammas (only films marked [curve] in --list-films, needs --film)")
    ap.add_argument("--grain", type=int, nargs="?", const=GRAIN_BLOCK, default=1, metavar="N", help=f"low-grain anchors: take the white/black percentiles from NxN block means instead of single pixels (default N = {GRAIN_BLOCK}, odd; without the option: off). Film grain, mostly in blue, otherwise pulls the white anchor and leaves a yellow cast; the output pixels are not smoothed")
    ap.add_argument("--list-films", action="store_true")
    ap.add_argument("--version", action="version", version=f"BallastConverter {version()}")
    a = ap.parse_args()

    if a.list_films:
        for (m, f), g in FILMS.items():
            print(f"{m}/{f:45s} {g[0]:.3f} {g[1]:.3f} {g[2]:.3f}" + ("  [curve]" if (m, f) in FILM_CURVES else ""))
        return
    if not a.input or not a.output:
        ap.error("specify input and output")

    try:
        gammas = resolve_gammas(a.film, a.gammas)
        if any(not (0.1 <= abs(g) <= 10.0) for g in gammas):
            raise ConversionError("gammas must be between 0.1 and 10")
        film_curve = None
        if a.datasheet_curve:
            film_curve = film_curve_path(a.film) if a.film and not a.gammas else None
            if not film_curve:
                raise ConversionError("--datasheet-curve needs --film with a film marked [curve] in --list-films")
        convert(a.input, a.output, gammas, a.in_curve, a.out_curve, a.p_black, a.p_bpoint, a.black, tuple(a.cc),
                not a.no_bpoint, a.bits, a.crop, a.stats_crop, a.embed_icc, a.subsample, film_curve=film_curve,
                film=a.film if not a.gammas else None, grain=a.grain)
    except ConversionError as e:
        raise SystemExit(f"error: {e}")


if __name__ == "__main__":
    main()
