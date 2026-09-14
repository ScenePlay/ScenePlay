"""Import every mapped model so Base.metadata knows the full schema (the Flask
boot imported the same set: models.tblTokenPositions, tblRollLog,
mediaMetadata explicitly; the rest through the route modules). models/video.py
is dead code and stays un-imported."""
from models import (campaigns, cronSchedule, genre, ledConfig, mediaMetadata,  # noqa: F401
                    music, musicScene, scenePattern, scenes, serverIP, serverRole,
                    status, tblRollLog, tblTokenPositions, ttrpg, user, videoMedia,
                    videoScene, wledPattern)
