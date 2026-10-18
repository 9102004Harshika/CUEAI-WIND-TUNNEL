import sys
import io

f = open('investigate_utf8.txt', 'w', encoding='utf-8')
sys.stdout = f
sys.stderr = f

from investigate_traces import investigate
import asyncio
if __name__ == "__main__":
    asyncio.run(investigate())
