#!/usr/bin/env python3

__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')


import ollama
from ollama import Client
import chromadb
from pathlib import Path
from utils import read_role
from pydantic import BaseModel

#ollama run hf.co/unsloth/Qwen2.5-Coder-14B-Instruct-128K-GGUF:Q4_K_M
#model = "hf.co/unsloth/Qwen2.5-Coder-14B-Instruct-128K-GGUF:Q4_K_M"
#model = "granite3.3:8b"
model = "gemma3:12b"
num_ctx = 131072


dbClient = chromadb.PersistentClient(path=f"chromadb-{model.replace('/', '_')}")
collection = dbClient.get_collection(name="roles")

client = Client(
    host="http://localhost:11434",
    timeout=180
)

def find_role_candidates(description):
    response = ollama.embed(
        model="all-minilm",
        input=description,
    )
    results = collection.query(
        query_embeddings=response.embeddings[0],
        n_results=10
    )
    return [{"role_name": role_name, "summary": results['documents'][0][i].split("\n")[0]} for i, role_name in enumerate(results["ids"][0])]



# an example input
# user_prompt = "Install Wordpress"
user_prompt = "Install Nginx and reboot the server"

response = ollama.generate(model=model, system=f"You're goal is to explain with a series of steps how you would address the user request. The output is a Markdown list. Each list entry is just a string. Do NOT use any special Markdown formatting. Each list entry should not be longer than 100 characters. Do NOT give example. Do NOT explain which command should be called. You're prefered Linux OS are RHEL9.", prompt=user_prompt, options={"num_ctx": 1024*10})
print(response.response)

final = []
for description in response.response.split("\n"):
    if description:
        final += find_role_candidates(description)

from pprint import pprint
pprint(final)

#final = []
#for i, role_name in enumerate(results["ids"][0]):
#    summary = results['documents'][0][i].split("\n")[0]
#    print(f"- {role_name} summary={summary[0:50]}... distance={results['distances'][0][i]}")
#
#    prompt = f"\nname={role_name}\nsummary: {summary}"
#    response = ollama.generate(model=model, system=f"User will share a role name and a summary. Return YES if it would be handy to answer the following need '{user_prompt}', and explain why", prompt=prompt, options={"num_ctx": 1024*10})
#    if response.response.startswith("YES"):
#        final.append({"role_name": role_name, "summary": summary})

from pprint import pprint
ansible_roles_prompt = "# Ansible Roles available\n\n"

for i in final:
    role_path = Path("roles") / i["role_name"]
    ansible_roles_prompt += f'## Ansible Role name: {i["role_name"]}\nsummary: {i["summary"]}\n'
    #ansible_roles_prompt += read_role(role_path)
    example_file = Path("examples") / i["role_name"]
    if example_file.is_file():
        ansible_roles_prompt += f'example:\n```\n{example_file.read_text()}```\n'
    ansible_roles_prompt += '\n'


class IdentifyRolesAnswer(BaseModel):
    roles: list[str]
    reason: str



response = ollama.generate(model=model, system=
                           "You are an Ansible expert. "
                           "User asks you to generate a Ansible Playbook than answer the "
                           "request. "
                           "You're job is to identify which Ansible roles are the best to answer the request. "
                           "Don't return multiple roles doing the same thing. "
                           "{ansible_roles_prompt}", prompt=user_prompt, options={"num_ctx": num_ctx},
                                   format=IdentifyRolesAnswer.model_json_schema(),
                           )
answer = IdentifyRolesAnswer.model_validate_json(response.response)


from pprint import pprint
pprint(answer)

ansible_roles_prompt = "# Ansible Roles available\n\n"

for role_name in answer.roles:
    role_path = Path("roles") / role_name
    ansible_roles_prompt += f'## Ansible Role name: {i["role_name"]}\nsummary: {i["summary"]}\n'
    ansible_roles_prompt += read_role(role_path)
    ansible_roles_prompt += '\n'


response = ollama.generate(model=model, system=
                           "You are an Ansible expert. "
                           "User asks you to generate a Ansible Playbook than answer the "
                           "request. "
                           "Answer with a valid Ansible Playbook. You're prefered Linux distribution is RHEL9. "
                           f"You must USE the following roles:\n {', '.join(answer.roles)}\n"
                           "DO NOT includes other roles. "
                           "include roles with the `ansible.builtin.include_role` module. "
                           "Do not duplicate tasks already done by the roles. "
                           "Use them when needed.\n {ansible_roles_prompt}", prompt=user_prompt, options={"num_ctx": num_ctx})
print(response.response)
