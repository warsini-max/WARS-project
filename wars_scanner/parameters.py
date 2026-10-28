"""Model parameters, copied from the Parameters sheet of WARS_TrackB_v0_6.xlsx.

Coefficients: Beneish (1999), Table 3, unweighted probit (8-variable model).
Thresholds A and B: Beneish (1999), Table 5 panel B.
Threshold C (-2.22) is NOT from Beneish (1999); the workbook marks it as not verified.

Every threshold is a SCREENING FLAG ONLY. It is not evidence that fraud or
manipulation occurred.
"""

COEFFICIENTS = {
    "const": -4.84,
    "DSRI": 0.920,
    "GMI": 0.528,
    "AQI": 0.404,
    "SGI": 0.892,
    "DEPI": 0.115,
    "SGAI": -0.172,
    "TATA": 4.679,
    "LVGI": -0.327,
}

THRESHOLDS = {
    # name: (value, verified_in_beneish_1999, note)
    "a": (-1.78, True, "Beneish (1999) Table 5 panel B, relative error costs 20:1 or 30:1"),
    "b": (-1.49, True, "Beneish (1999) Table 5 panel B, relative error costs 10:1"),
    "c": (-2.22, False, "Not in Beneish (1999); attributed in secondary literature to later authors, not read"),
}

ABOVE = "Above threshold (screening flag only)"
BELOW = "Below threshold"

NON_PPE_STATUSES = ("NONE_PRESENT", "ALL_DISCLOSED", "PARTIAL_UNDISCLOSED")
