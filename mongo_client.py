# External imports
from pymongo import MongoClient
from dotenv import load_dotenv
import os

# Load the environment variables
load_dotenv()


class AtlasClient ():
    """
    A class to interact with MongoDB Atlas.

    Attributes:
    -----------
    altas_uri: str
        The URI for the MongoDB Atlas.    
    dbname: str
        The name of the database.
    mongodb_client: MongoClient
        The MongoDB client.
    database: Database
        The MongoDB database.

    Methods:
    --------
    ping()
        Pings the MongoDB Atlas.
    get_collection(collection_name)
        Gets a collection from the database.
    find(collection_name, filter={}, limit=0)
        Finds documents in a collection.
    update(collection_name, filter, update)
        Updates documents in a collection.
    insert(collection_name, data)
        Inserts a document in a collection.
    delete(collection_name, filter)
        Deletes a document in a collection.
    aggregate(collection_name, pipeline)
        Aggregates documents in a collection.
    """

    def __init__(self, altas_uri=os.getenv("MONGO_URI"), dbname=os.getenv("MONGO_DB")):
        """
        Constructor for the AtlasClient class.

        Parameters:
        -----------
        altas_uri: str
            The URI for the MongoDB Atlas.
        dbname: str
            The name of the database.    
        """
        self.mongodb_client = MongoClient(altas_uri)
        self.database = self.mongodb_client[dbname]

    def ping(self):
        """
        Pings the MongoDB Atlas.
        """
        self.mongodb_client.admin.command('ping')

    def get_collection(self, collection_name):
        """
        Gets a collection from the database.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.

        Returns:
        --------
        collection: Collection
        """
        collection = self.database[collection_name]
        return collection

    def find(self, collection_name, filter={}, limit=0):
        """
        Finds documents in a collection.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.
        filter: dict
            The filter to apply.
        limit: int
            The limit of documents to return.

        Returns:
        --------
        items: list
            The list of documents.
        """
        collection = self.database[collection_name]
        items = list(collection.find(filter=filter, limit=limit))
        return items

    def update(self, collection_name, filter, update):
        """
        Updates documents in a collection.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.
        filter: dict
            The filter to apply.
        update: dict
            The update to apply.

        Returns:
        --------
        bool: True if successful, False otherwise.
            """
        collection = self.database[collection_name]
        collection.update_one(filter, update)
        return True

    def insert(self, collection_name, data):
        """
        Inserts a document in a collection.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.
        data: dict
            The data to insert.

        Returns:
        --------
        id: ObjectId
            The id of the inserted document.
        """

        collection = self.database[collection_name]
        id = collection.insert_one(data).inserted_id
        return id

    def delete(self, collection_name, filter):
        """
        Deletes a document in a collection.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.
        filter: dict
            The filter to apply.

        Returns:
        --------
            bool: True if successful, False otherwise.
        """
        collection = self.database[collection_name]
        collection.delete_one(filter)
        return True

    def aggregate(self, collection_name, pipeline):
        """
        Aggregates documents in a collection.

        Parameters:
        -----------
        collection_name: str
            The name of the collection.
        pipeline: list
            The aggregation pipeline.

        Returns:
        --------
        list: The list of documents.
        """
        collection = self.database[collection_name]
        return list(collection.aggregate(pipeline))
