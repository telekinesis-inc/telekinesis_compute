import asyncio
import telekinesis as tk
import os
import json
{{IMPORTS}}

class Dict(dict):
    def update(*args):
        raise PermissionError
    def pop(*args):
        raise PermissionError
    def popitem(*args):
        raise PermissionError
    def clear(*args):
        raise PermissionError

async def executor(code, namespace={}):
    prefix = 'async def _wrapper(_new):\n'
    content = ('\n'+code).replace('\n', '\n    ')
    suffix = """
    for _var in dir():
        if _var[0] != '_':
            _new[_var] = eval(_var)"""
    exec(prefix+content+suffix, namespace)
    new_vars = {}
    await namespace['_wrapper'](new_vars)
    return Dict(new_vars)

async def main():
    print('starting')
    e = asyncio.Event()

    with open('../session_key.pem', 'w') as file:
        file.write(os.environ['PRIVATEKEY'])

    entrypoint = await tk.Entrypoint('ws://127.0.0.1:8777', '../session_key.pem')
    route = tk.Route(**json.loads(os.environ['ROUTE']))

    await tk.Telekinesis(route, entrypoint._session)({'executor': executor, 'stop': lambda: e.set()})

    print('running')

    await e.wait()
    print('stopping')

asyncio.run(main())