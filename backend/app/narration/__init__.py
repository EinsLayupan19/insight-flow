"""Optional AI narration of key findings: a local model rewrites computed findings as a short summary.

The findings never depend on it. The narrator only sees the findings' own text and figures
(never CSV rows, order IDs, or line numbers), its output is checked against those figures,
and anything that fails the checks is replaced by a template summary.
"""
