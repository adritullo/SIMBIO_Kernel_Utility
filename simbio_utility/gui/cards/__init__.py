"""Card registry. To add a function to the app: write a ``Card`` subclass and list it in ``CARDS``."""
from .geometry_card import GeometryCard
from .time_card import TimeCard

CARDS = [TimeCard, GeometryCard]  # sidebar order
