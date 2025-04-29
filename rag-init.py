#!/usr/bin/env python3

__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import httpx
import httpcore
import yaml
import re
import json
import ollama
import chromadb
from textwrap import dedent
from typing import Annotated
from pydantic import AfterValidator, BaseModel

from utils import read_role

#model = "qwen2.5:14b"
#ollama run hf.co/unsloth/Qwen2.5-Coder-14B-Instruct-128K-GGUF:Q4_K_M
#model = "hf.co/unsloth/Qwen2.5-Coder-14B-Instruct-128K-GGUF:Q4_K_M"
model = "gemma3:12b"
num_ctx = 131072

#model = "granite3.3:8b"
#num_ctx = 131072

dbClient = chromadb.PersistentClient(path=f"chromadb-{model.replace('/', '_')}")
collection = dbClient.get_or_create_collection(name="roles")


from pathlib import Path
from pydantic import BaseModel

from ollama import chat
from ollama import Client


workspace = Path(".")


def add_to_db(dbClient, role_name, summary: str, quality: int):
    response = ollama.embed(model="all-minilm", input=summary)
    embeddings = response["embeddings"]
    collection.add(
        ids=[role_name],
        embeddings=embeddings,
        metadatas=[{"quality": quality}],
        documents=[summary]
    )

dbClient = chromadb.PersistentClient(path="chromadb")
client = Client(
    host="http://localhost:11434",
    timeout=300,
)


def get_quality(role_content) -> int|None:
    def isBetween0And100(value: int):
        if value <= 100:
            return value
        raise ValueError("Unexpected rating")

    class QualityAnswer(BaseModel):
        rating: Annotated[int,AfterValidator(isBetween0And100)]
        reason: str

    for _ in range(3):
        try:
            response = client.generate(model=model, system=
                                   "User will share the content of an Ansible role, file by file. "
                                   "Read the whole content first. "
                                   "Return a number between 0 and 100 based on the quality of the role. "
                                   "0 for a poor quality Ansible role, and 100, for a great role that can "
                                   "be reused in various context and resolve problems.", prompt=role_content, stream=False, options={"num_ctx": num_ctx}, format=QualityAnswer.model_json_schema(),)
        except (httpx.ReadTimeout, httpcore.ReadTimeout):
            print("timeout")
            return

        answer = QualityAnswer.model_validate_json(response.response)
        print(answer)
        if 0 <= answer.rating <= 100:
            return answer.rating


def prepare_example(role_name, role_content) -> str:

    base_prompt_example = """
    Read the whole content first.
    Return an example that uses the `ansible.builtin.include_role` task.
    Do NOT set the `tasks_from` parameter.
    Quote the example in between ``` quotes (Markdown).

    This is an example of a call of `ansible.builtin.include_role`, the role is called `myrole`:
    ```
    - name: Include role myrole
      ansible.builtin.include_role:
        name: myrole
    ```

    and another example with a variable assigment:

    ```
    - name: Include role myrole
      ansible.builtin.include_role:
        name: myrole
      vars:
        rolevar1: value from task
    ```

    If the role expects some arguments, show some example of how to use them.
    Include a short list of public parameters expected by the role and describe each of them.

    Do NOT write a full playbook. Just Ansible tasks.
    """


    for _ in range(15):
        response = client.generate(model=model, system=
                               f"User will share the content of an Ansible role called `{role_name}`, "
                               f"file by file. {dedent(base_prompt_example)}"
, prompt=role_content, stream=False, options={"num_ctx": num_ctx, "temperature": 1})

        print(response.response)
        #if "tasks_from" in response.response:
        #    continue
        matches = re.findall(r".*?```(yaml|yml|)\n+(.+)```", response.response, re.MULTILINE | re.DOTALL)
        yaml_candidates = [response.response] + [m[1] for m in matches]
        for c in yaml_candidates:
            try:
                task = yaml.safe_load(c)
                if task[0]["ansible.builtin.include_role"]["name"] != role_name:
                    continue
                if len(task[0]["ansible.builtin.include_role"].keys()) > 1:
                    print("Wrong keys")
                    continue
            except (yaml.YAMLError, KeyError, TypeError, IndexError) as e:
                continue
            print("GOOD!")
            return response.response
    print(f"Cannot generate example for {role_name}")



def is_good_summary(summary: str):
    response = client.generate(model='granite3.3:8b', system="User will share a text and you we decide if it's a good summary of a function that can be shared with a person. You MUST ONLY answer with YES or NO. If the answer is NO, add an extra line to explain why.", prompt=summary, stream=False)
    return response.response.startswith("YES")


if __name__ == "__main__":
    for role_path in Path("roles").iterdir():
        print(f"\n# {role_path}\n")
        if found := collection.get(ids=[role_path.name]):
            if found["ids"]:
                print("Skip, already indexed")
                continue

        role_content = read_role(role_path)

        print(f"role_content length={len(role_content)}")
        if len(role_content) > 200000:
            print("Too big")
            continue
        quality = get_quality(role_content=role_content)
        print(f"quality={quality}")
        if not quality or quality < 60:
            print("Skip, quality too low")
            continue
        example_path = Path("examples") / role_path.name
        if not example_path.exists():
            if example_content := prepare_example(role_path.name, role_content=role_content):
                example_path.write_text(example_content)
        for _ in range(5):
            response = client.generate(model=model, system=
                                       "User will share the content of an Ansible role, file by file. Read "
                                       "the whole content first. Give a 3 lines long summary that focus on "
                                       "the features. The summary should NOT give the role name. The summary "
                                       "should NOT cover each file. The SUMMARY MUST explain the most "
                                       "important parameters.", prompt=role_content, stream=False, options={"num_ctx": num_ctx})
            if is_good_summary(response.response):
                add_to_db(dbClient, role_path.name, summary=response.response, quality=quality)
                break
        else:
            print("Max retry")
