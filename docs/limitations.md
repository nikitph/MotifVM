# MotifVM Limitations

- The current domains are deliberately narrow: DCCB CRAR checks and security-focused code review.
- Repository review uses checked-in diffs or patch files; it does not yet perform full Git history analysis.
- The code-review detector is deterministic and conservative; it is not a complete static analyzer.
- Authority sources are checked-in snapshots, not live regulatory retrievals.
- DeepSeek integration is bounded to structured calls and non-critical narrative emission in this milestone.
- Audit-pack verification checks internal consistency; it does not certify legal, financial, or security completeness.
