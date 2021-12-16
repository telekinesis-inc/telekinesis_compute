import os
import importlib
import json
import asyncio
import telekinesis as tk
import docker

def prepare_python_files(path, *dependencies):
    dockerbase = importlib.resources.read_text(__package__, f"Dockerfile_python")
    dockerfile = dockerbase.replace('{{DEPENDENCIES}}', '\n'.join('RUN pip install '+ d for d in dependencies))

    with open(os.path.join(path, 'Dockerfile'), 'w') as file_out:
        file_out.write(dockerfile)

    scriptbase = importlib.resources.read_text(__package__, "script_base.py")
    script = scriptbase.replace('{{IMPORTS}}', '\n'.join('import '+ d for d in dependencies))

    with open(os.path.join(path, 'script.py'), 'w') as file_out:
        file_out.write(script)

def prepare_js_files(path, *dependencies):
    dockerbase = importlib.resources.read_text(__package__, "Dockerfile_js")
    dockerfile = dockerbase.replace('{{DEPENDENCIES}}', '\n'.join('RUN npm install '+ d for d in dependencies))

    with open(os.path.join(path, 'Dockerfile'), 'w') as file_out:
        file_out.write(dockerfile)

    scriptbase = importlib.resources.read_text(__package__, "script_base.js")
    script = scriptbase.replace('{{IMPORTS}}', '\n'.join(f'require({d});' for d in dependencies))

    with open(os.path.join(path, 'script.js'), 'w') as file_out:
        file_out.write(script)

class AppManager:
    def __init__(self, session, path, url=None):
        self.running = {}
        self.ready = {}
        self.client = docker.from_env()
        self.url = url or list(session.connections)[0].url
        self._session = session
        self.path = path

    async def build_image(self, language, *dependencies):
        tag = '-'.join(['tk', language, *dependencies])
        if language == 'python':
            prepare_python_files(self.path, *dependencies)
        elif language == 'js':
            prepare_js_files(self.path, *dependencies)
        else:
            raise NotImplementedError("Only implemented languages are 'python' and 'js'")

        
        cmd = f'docker build -t {tag} {self.path}'
        
        build = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE
        )
        await build.stdout.read()
        # await self.client.images.build(path_dockerfile='./docker_telekinesis_python/', tag=tag)

    async def create_container(self, language='python', *dependencies):
        tag = '-'.join(['tk', language, *dependencies])

        if not self.client.images.list(name=tag):
            self.build_image(language, *dependencies)

        def create_callbackable():
            e = asyncio.Event()
            data = {}

            async def awaiter():
                await e.wait()
                return data['data']

            return (awaiter, lambda x: data.update({'data': x}) or e.set())

        awaiter, callback = create_callbackable()
        
        client_session = tk.Session()

        route = await tk.Telekinesis(callback, self._session)._delegate(client_session.session_key.public_serial())

        environment=[
            "URL='"+self.url+"'",
            "ROUTE='"+json.dumps(route.to_dict())+"'",
            "PRIVATEKEY='"+client_session.session_key._private_serial().decode().strip('\n').replace('\n','\\')+"'"]
        
        cmd = f"docker run -e {' -e '.join(environment)} -d --rm --network=host -l telekinesis-compute {tag}"
        
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE
        )

        container_id = (await process.stdout.read()).decode().replace('\n','')

        d = await awaiter()
        # container = self.client.containers.get(container_id)
        
        d.update({'container_id': container_id})
        
        return d

    async def clear_containers(self):
        [c.stop(timeout=0) for c in self.client.containers.list(all=True, filters={'label': 'telekinesis-compute'})]
        [c.remove() for c in self.client.containers.list(all=True, filters={'label': 'telekinesis-compute'})]

        return self.client.images.prune()
    
    async def get_instance(self, name, language='python', *imports, upgrade=False):
        if not self.ready.get('-'.join(imports)):
            print('awaiting provisioning')
            await self.provision(1, language, *imports, upgade=upgrade)
        d = self.ready['-'.join([language, *imports])].pop()
        async def delayed_provisioning():
            await asyncio.sleep(1)
            await self.provision(1, language, *imports, upgrade=upgrade)
            
        asyncio.create_task(delayed_provisioning())
        self.running[name] = d
        return d

    async def provision(self, number, language='python', *imports, upgade=False):
        print('provisioning', number)
        tag = '-'.join(['tk', language, *imports])
        if not tag in self.ready:
            self.ready[tag] = []

        if upgade:
            await self.build_image(language, *imports)
        self.ready[tag].extend(
            await asyncio.gather(*[self.create_container(language, *imports) for _ in range(number)])
        )
    