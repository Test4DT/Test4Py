import os
import re
from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from transformers import AutoTokenizer, AutoModel
import torch
from typing import List
import chromadb


class HuggingFaceEmbedder(Embeddings):
    def embed_query(self, text: str) -> List[float]:
        """Embed query text.

        Args:
            text: Text to embed.

        Returns:
            Embedding as a list of floats.
        """
        text = self.embed_instruction + text.replace("\n", " ")

        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512, **self.encode_kwargs)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)

        embedding = torch.mean(outputs.last_hidden_state, dim=1).squeeze()

        return embedding.tolist()

    def __init__(self, model_name_or_path: str, embed_instruction: str = "", show_progress: bool = False,
                 encode_kwargs=None):
        if encode_kwargs is None:
            encode_kwargs = {}
        self.embed_instruction = embed_instruction
        self.show_progress = show_progress
        self.encode_kwargs = encode_kwargs
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path, local_files_only=True)
        self.model = AutoModel.from_pretrained(model_name_or_path, local_files_only=True).to(self.device)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        texts = [self.embed_instruction + t.replace("\n", " ") for t in texts]

        inputs = self.tokenizer(texts, padding=True, truncation=True, return_tensors="pt", max_length=512, **self.encode_kwargs)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            outputs = self.model(**inputs)

        embeddings = torch.mean(outputs.last_hidden_state, dim=1)

        return embeddings.tolist()


def find_topK_message(name, messages, query_vector, k=1):
    ids = []
    vectors = []
    name = re.sub(r"[^a-zA-Z]", "", name)[-30:]
    collection = client.create_collection(name)
    for index, value in enumerate(messages):
        ids.append(str(index))
        vectors.append(value.vector)
    collection.add(
        embeddings=vectors,
        ids=ids
    )
    try:
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=k
        )
    except RuntimeError:
        client.delete_collection(name)
        return messages
    client.delete_collection(name)

    top_k = []
    for index in results['ids'][0]:
        top_k.append(messages[int(index)])
    return top_k


class FunctionDatabase:
    def __init__(self):
        self.collection = client.create_collection('functions_database')
        self.functions = []

    def init(self, project):
        ids = []
        vectors = []
        for file_message in project.file_messages:
            for function in file_message.functions:
                if function.summary is None:
                    continue
                ids.append(str(len(self.functions)))
                self.functions.append(function)
                vectors.append(embedder.embed_query(function.summary))
        self.collection.add(
            embeddings=vectors,
            ids=ids
        )

    def query(self, query, k=3):
        query_vector = embedder.embed_query(query)
        try:
            results = self.collection.query(
                query_embeddings=[query_vector],
                n_results=k
            )
        except RuntimeError:
            return []

        top_k = []
        for index in results['ids'][0]:
            top_k.append(self.functions[int(index)])
        return top_k


load_dotenv()
embedder = HuggingFaceEmbedder(model_name_or_path=os.getenv('TRANSFORMER_PATH') or '')
client = chromadb.Client()
function_database = FunctionDatabase()
