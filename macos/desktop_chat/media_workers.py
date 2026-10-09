"""Bounded online thumbnail work; workers never call Tk."""
from concurrent.futures import ThreadPoolExecutor

thumbnail_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="online-thumbnail")
storage_workers = ThreadPoolExecutor(max_workers=1, thread_name_prefix="online-cache")
