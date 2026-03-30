"""Ship pipeline — verify, commit, push, PR/merge, deploy.

Shared implementation used by both the /ship CLI skill and the
dashboard Ship button. Python handles scheduling and state;
LLMs handle judgment (feedback classification).
"""
