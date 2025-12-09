import asyncio


params = {1:'bebra', 2: "piska",3:'bebra', 4: "piska"}

test = [1,2]
temp = []

async def bebra():
    asyncio.gather(*[test1(param) for param in params.keys()])

    
async def test1(param):
    if param not in test:
        print(param)
        temp.append(param)

if __name__ == '__main__':
    asyncio.run(bebra())
    print(temp)
    