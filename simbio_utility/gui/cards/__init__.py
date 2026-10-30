"""Card registry. To add a function to the app: write a ``Card`` subclass and list it in ``CARDS``."""
from .download_card import DownloadCard
from .geometry_card import GeometryCard
from .time_card import TimeCard

CARDS = [TimeCard, GeometryCard, DownloadCard]  # sidebar order
