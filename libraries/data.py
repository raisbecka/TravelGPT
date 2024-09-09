import json
import re
import sqlite3
import sys
from typing import Dict, List, Optional, Tuple
import numpy as np
from langchain.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import ValidationError, BaseModel, Field

np.set_printoptions(threshold = np.inf)

# NOT USED
class Country(BaseModel):
    """Information about a country."""
    name: str = Field(description="Name of the country")

# NOT USED
class Countries(BaseModel):
    """A list of countries."""
    people: List[Country]    
    
class Item(BaseModel):
    """Information about an item."""
    item_title: str = Field(description="A descriptive title for this list item")
    proper_title: str = Field(description="The actual title of the place, business, or thing (for searching on Google)")
    description: str = Field(description="Description of the list item")
    is_specific_location: bool = Field(description="Whether the item is a specific location on the map")
    street_address: Optional[str] = Field(description="Street address of the item, if applicable", default="")
    type: str = Field(description="Type of the item (e.g., activity, food, accommodation, day trip)")

class ItemList(BaseModel):
    """A list of items with a meaningful title."""
    list_title: str = Field(description="Meaningful title for this specific list of items")
    items: List[Item] = Field(description="List of items asked for")
    
class ListsContainer(BaseModel):
    """A container for a list of lists of items."""
    lists: List[ItemList] = Field(description="The main list of requested lists")
    
################## UTILITY METHODS ##################

def json_to_model(model, json_data):
    model_instance = model(**json_data)
    return model_instance
    

################# DATABASE LAYER #################
def save_data_to_db(db_path: str, data: List[Tuple]):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    for embedding, country, destination, pydantic_obj, api_responses in data:
        embedding_bytes = embedding.tobytes() if embedding is not None else None
        cursor.execute('''
        INSERT INTO places (embedding, country, destination, proper_title, pydantic_data)
        VALUES (?, ?, ?, ?, ?)
        ''', (embedding_bytes, country, destination, pydantic_obj.proper_title, pydantic_obj.json()))
        
        place_id = cursor.lastrowid
        
        if api_responses:
            for response_type, response_data in api_responses.items():
                cursor.execute('''
                INSERT INTO google_api_responses (place_id, response_type, response_data)
                VALUES (?, ?, ?)
                ''', (place_id, response_type, json.dumps(response_data)))
    
    conn.commit()
    conn.close()
    
    
def load_data_from_db(db_path: str) -> List[Tuple]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS places (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        embedding BLOB,
        country TEXT,
        destination TEXT,
        proper_title TEXT,
        pydantic_data TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS google_api_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        place_id INTEGER,
        response_type TEXT,
        response_data TEXT,
        FOREIGN KEY(place_id) REFERENCES places(id)
    )
    ''')
    
    cursor.execute('SELECT id, embedding, country, destination, proper_title, pydantic_data FROM places')
    rows = cursor.fetchall()
    
    data = []
    for row in rows:
        place_id, embedding_bytes, country, destination, proper_title, pydantic_data = row
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32) if embedding_bytes is not None else None
        pydantic_obj = Item.parse_raw(pydantic_data)
        
        cursor.execute('SELECT response_type, response_data FROM google_api_responses WHERE place_id = ?', (place_id,))
        api_rows = cursor.fetchall()
        
        api_responses = {}
        for api_row in api_rows:
            response_type, response_data = api_row
            api_responses[response_type] = json.loads(response_data)
        
        data.append((embedding, country, destination, pydantic_obj, api_responses))
    
    conn.close()
    return data


def save_general_preferences(db_path: str, country: str, preferences: Dict):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR REPLACE INTO general_preferences (country, preferences)
    VALUES (?, ?)
    ''', (country, json.dumps(preferences)))
    
    conn.commit()
    conn.close()

def load_general_preferences(db_path: str, country: str) -> Dict:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS general_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT UNIQUE,
        preferences TEXT
    )
    ''')
    
    cursor.execute('SELECT preferences FROM general_preferences WHERE country = ?', (country,))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return json.loads(row[0])
    return {}

def save_destination_preferences(db_path: str, country: str, destination: str, preferences: Dict):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    INSERT OR REPLACE INTO destination_preferences (country, destination, preferences)
    VALUES (?, ?, ?)
    ''', (country, destination, json.dumps(preferences)))
    
    conn.commit()
    conn.close()

def load_destination_preferences(db_path: str, country: str, destination: str) -> Dict:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS destination_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT,
        destination TEXT,
        preferences TEXT,
        UNIQUE(country, destination)
    )
    ''')
    
    cursor.execute('SELECT preferences FROM destination_preferences WHERE country = ? AND destination = ?', (country, destination))
    row = cursor.fetchone()
    
    conn.close()
    
    if row:
        return json.loads(row[0])
    return {}

def reset_database(db_path: str):
    """Drop all tables from the SQLite database and recreate them."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Drop all existing tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table[0]}")

    # Recreate tables
    cursor.execute('''
    CREATE TABLE places (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        embedding BLOB,
        country TEXT,
        destination TEXT,
        proper_title TEXT,
        street_address TEXT,
        pydantic_data TEXT,
        type TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE google_api_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        place_id INTEGER,
        response_type TEXT,
        response_data TEXT,
        FOREIGN KEY(place_id) REFERENCES places(id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE general_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT UNIQUE,
        preferences TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE destination_preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        country TEXT,
        destination TEXT,
        preferences TEXT,
        UNIQUE(country, destination)
    )
    ''')

    conn.commit()
    conn.close()

def clear_place_data(db_path: str):
    """Clear all place-related records from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS places")
    cursor.execute("DROP TABLE IF EXISTS google_api_responses")
    conn.commit()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS places (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        embedding BLOB,
        country TEXT,
        destination TEXT,
        proper_title TEXT,
        pydantic_data TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS google_api_responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        place_id INTEGER,
        response_type TEXT,
        response_data TEXT,
        FOREIGN KEY(place_id) REFERENCES places(id)
    )
    ''')

    conn.commit()
    conn.close()

def clear_preferences(db_path: str):
    """Clear all preference-related records from the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM general_preferences")
    cursor.execute("DELETE FROM destination_preferences")

    conn.commit()
    conn.close()
