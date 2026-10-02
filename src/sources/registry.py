from src.sources.amazon_in import AmazonInSource
from src.sources.dlcompare import DlcompareSource
from src.sources.egiftcards_nz import EgiftcardsNzSource
from src.sources.eneba import EnebaSource
from src.sources.matiex import MatiexSource
from src.sources.seagm import SeagmSource
from src.sources.simplygaming import SimplygamingSource

ALL_SOURCES = [
    DlcompareSource, SeagmSource, SimplygamingSource, EnebaSource,
    EgiftcardsNzSource, MatiexSource, AmazonInSource,
]
