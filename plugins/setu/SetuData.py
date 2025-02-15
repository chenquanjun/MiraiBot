import json
import asyncio
import aiohttp
import PIL.Image
from io import BytesIO
from pathlib import Path
from typing import List, Set
from datetime import datetime, timedelta
from pydantic import BaseModel, validator, ValidationError
from urllib.parse import urlparse

from config import data_path, setu_apikey, setu_proxy, setu_r18

Path(data_path).mkdir(exist_ok=True)
SAVE_FILE = Path(data_path).joinpath('setu.json')
FREQUENCY_FILE = Path(data_path).joinpath('setu_frequency.gif')

FrequencyBytes = None

def LoadFrequencyFile():
    global FrequencyBytes
    if FrequencyBytes is None:
        with open(FREQUENCY_FILE,"rb") as f:
            FrequencyBytes = f.read()
    return FrequencyBytes

class SetuData(BaseModel):
    pid: int = None
    p: int = None
    uid: int = None
    title: str = None
    author: str = None
    url: str
    r18: bool = None
    width: int = None
    height: int = None
    tags: List[str] = None

    @property
    def purl(self) -> str:
        return 'https://www.pixiv.net/artworks/{}'.format(Path(urlparse(self.url).path).stem.split('_')[0])

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.url == other.url
        else:
            return False

    def __hash__(self):
        return hash(self.url)

    def save(self) -> None:
        """保存至文件"""
        SetuDatabase.save(self)

    async def get(self, check_size: bool = True) -> bytes:
        """从网络获取图像"""
        try:
            headers = {'Referer': 'https://www.pixiv.net/'} if 'i.pximg.net' in self.url else {}
            async with aiohttp.request('GET', self.url, headers=headers, timeout=aiohttp.ClientTimeout(10)) as resp:
                img_bytes: bytes = await resp.read()
            if check_size:
                img: PIL.Image.Image = PIL.Image.open(BytesIO(initial_bytes=img_bytes))
                if img.size != (self.width, self.height):
                    raise ValueError(f'Image Size Error: expected {(self.width, self.height)} but got {img.size}')
        except (asyncio.TimeoutError, ValueError) as e:
            raise e
        except PIL.UnidentifiedImageError:
            raise ValueError(f'Image load fail {str(img_bytes[:20])}...')
        return img_bytes


class SetuDatabase(BaseModel):
    __root__: Set[SetuData] = set()

    @classmethod
    def load_from_file(cls) -> "SetuDatabase":
        try:
            db: SetuDatabase = cls.parse_file(SAVE_FILE)
        except (FileNotFoundError, json.JSONDecodeError, ValidationError):
            db = cls()
        return db

    def save_to_file(self) -> None:
        with SAVE_FILE.open('w', encoding='utf8') as f:
            json.dump([data.dict() for data in self.__root__], f, ensure_ascii=False, indent=2)

    @classmethod
    def save(cls, *data_array: SetuData) -> None:
        db: SetuDatabase = cls.load_from_file()
        for data in data_array:
            db.__root__.discard(data)
            db.__root__.add(data)
        db.save_to_file()


class SetuResp(BaseModel):
    code: int
    msg: str
    quota: int = 0
    quota_min_ttl: int = 0
    time_to_recover: datetime = None
    count: int = 0
    data: List[SetuData] = []

    @validator('time_to_recover', pre=True, always=True)
    def get_ttr(cls, _, values):
        quota_min_ttl: int = values['quota_min_ttl']
        return datetime.now() + timedelta(seconds=quota_min_ttl)

    def save(self) -> None:
        SetuDatabase.save(*self.data)

    @staticmethod
    async def get(keyword='') -> "SetuResp":
        api_url = 'https://api.lolicon.app/setu/'
        params = {
            "apikey": setu_apikey,
            "r18": setu_r18,
            "keyword": keyword,
            "num": 10,
            "proxy": setu_proxy,
            "size1200": 'false'
        }
        async with aiohttp.request('GET', api_url, params=params) as response:
            setu_j = await response.read()
        resp: SetuResp = SetuResp.parse_raw(setu_j)
        resp.save()
        return resp
