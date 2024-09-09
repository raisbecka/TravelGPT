import argparse
import json
import re
import sys
import time
import google.generativeai as genai
import os
import googlemaps
import pydantic
from pydantic import ValidationError
from rich.console import Console
from interface import load_interface
from libraries.data import * 
from tools import generate_embedding, get_place_details, search_data_for_item

console = Console()

MODEL_NAME = "gemini-1.5-flash"
EMBEDDING_MODEL_NAME = "text-multilingual-embedding-002"

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
gmaps = googlemaps.Client(key=os.environ["GMAPS_API_KEY"])

def parse_arguments():
    parser = argparse.ArgumentParser(description="Travel information gathering and processing script")
    parser.add_argument("-sk", "--skip-research", action="store_true",
                        help="Skip the main loop that prompts Google Gemini and parses the responses")
    parser.add_argument("-cd", "--clear-data", action="store_true",
                        help="Clear all place-related records from the database before executing the script")
    parser.add_argument("-cf", "--clear-prefs", action="store_true",
                        help="Clear all preference-related records from the database before executing the script")
    parser.add_argument("-r", "--reset-all", action="store_true",
                        help="Drop all tables from the SQLite database and then run the script as normal")
    return parser.parse_args()

def main():
    args = parse_arguments()
    db_path = 'places.db'

    if args.reset_all:
        reset_database(db_path)
    elif args.clear_data:
        clear_place_data(db_path)
    elif args.clear_prefs:
        clear_preferences(db_path)

    # Load existing data
    data = load_data_from_db(db_path)

    def call_gemini(prompt, schema):
        """Calls the Gemini API with the provided prompt and returns the response."""
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": schema
            }
        )
        response = model.generate_content(f"{prompt}")
        return response


    def ask_user_question(question):
        """Asks a general question and returns the response."""

        while True:
            console.print(f"\n[cyan]{question}")
            response = input()
            
            if len(response) > 0:
                return response
            else:
                console.print("[red]Please provide a valid response to the question.")
                time.sleep(1)


    def get_destination_specific_info(destination, country, question, gen_info, dest_info, question_type):
        
        # Compile user responses into a context variable to be used when prompting gemini
        user_context = f"""Please use the following general {question_type} preferences to guide your suggestions when answering the question: 
        {gen_info.get(question_type, "Nothing specified.")}
        """
        
        if dest_info:
            user_context += f"""\n
            In addition, please use the following {destination}-specific {question_type} preferences: 
            {dest_info.get(question_type, "Nothing specified.")}
            """
        
        # Add conditional instructions based on the question type to be added when prompting gemini
        conditional_instructions = ""
        if question_type == 'food':
            conditional_instructions = "Lastly, For each item in the lists, include a line below the title and distance that provides the approximate price range if known."
        if question_type == 'accomodation':
            conditional_instructions = "Lastly, for each item in the lists, include what the cancellation policy is (if known)."
        
        """
        # Enforce structure of the response
        json_model = model_to_json(ListsContainer)
        response_structure = f'.Please provide a response in a structured JSON format that matches the following model: {json_model}'
        """
        
        # Create the prompt that will be sent to the Gemini API
        prompt = f"""
        Please use Google Maps, Google Search and/or Google Places to assist with answering the following question regarding {destination}, {country}. 
        
        HERE IS THE QUESTION: \"{question}\".
        
        {user_context}
        
        {conditional_instructions}
        
        Please provide your response below:
        """

        # Call API and return response
        while True:
            response = call_gemini(prompt, ItemList)
            if response:
                response_dict = json.loads(response.text)
                try:
                    resp_obj = json_to_model(ItemList, response_dict)
                    return resp_obj
                except ValidationError as e:
                    console.print(f"[red]Validation error: {e}[/red] [yellow]\nTrying again![/yellow]")
            else:
                sys.exit(1)


    # List of countries to get travel info for
    countries = ["Japan"]

    # List of destinations in each country to get travel info for
    destinations = {
        "Japan": ["Tokyo", "Kyoto", "Kanazawa", "Osaka"],
    }

    # destination_info is a dictionary that will store information for each destination
    #prompt_types = ['activity', 'accomodation', 'food', 'day trip']
    prompt_types = ['activity']
    trip_info = {}
    gen_info = {}

    instructions = {
        #"TEST": "Please suggest visiting the Imperial Palace in {destination}, {country} in 5 different ways. In other words, suggest the same activity (ie. visiting the Imperial Palace), but word the suggestion slightly differently each time.",
        "activity": "Provide a list of 40 unique tourist attractions in {destination}, {country} that have specific locations mappable on Google Maps. These attractions can simply be trendy or interesting businesses, venues, parks, etc. and can be free or paid. Include the full name and street address for each suggestion. Don't recommend activities that involve eating a meal.",
        "food": "Provide a list of 30 unique places to eat while traveling in {destination}, {country} that have specific locations mappable on Google Maps. Include the full name and street address for each suggestion. Make recommendations ranging from expensive places, to regular priced places, and lastly cheap eats and/or street food. Do NOT recommend general types of food, or food items, etc. All suggestions should be unique places that are actual businesses. All suggestions should have a valid place ID for Google Maps.",
        "accomodation": "Considering proximity to central {destination}, {country}, please suggest 10 accommodation options - either hostels or hotels - that are relatively affordable. Recommend specific, unique businesses with locations that are mappable on Google Maps. Include the full name and street address for each suggestion. Small shared accommodations are acceptable, although private hostel or hotel rooms are preferred. Lastly, for all options, give preference to places that have lenient cancellation policies.",
        "day trip": "Please suggest a list of 5 day trips that I can take while traveling in {destination}, {country} as a tourist. Each suggestion should be for a specific, unique location that is mappable on Google Maps. Include the full name and street address for each suggestion.Do not make suggestions that involve greater than 2 hours of travel from {destination}.",
    }

    # Update the general preferences section
    gen_info = load_general_preferences(db_path, countries[0])  # Assuming one country for simplicity

    if not gen_info:
        # Start asking general questions
        gen_info['activity'] = ask_user_question("What sort of activities are you looking to do on your trip?")
        gen_info['accomodation'] = ask_user_question("What sort of accomodations do you prefer?")
        gen_info['food'] = ask_user_question("What kind of food do you like?")
        gen_info['day trip'] = ask_user_question("Are you interested in any specific day trips? Or types of day trips?")

        # Save responses to database
        save_general_preferences(db_path, countries[0], gen_info)

    # Update the destination-specific preferences section
    for country in countries:
        for destination in destinations[country]:
            dest_info = load_destination_preferences(db_path, country, destination)

            if not dest_info:
                # Get date range for destination
                dest_info['start_date'] = ask_user_question(f"What is the start date for your trip to {destination}, {country} (MM/DD/YYYY)?")
                dest_info['end_date'] = ask_user_question(f"What is the end date for your trip to {destination}, {country} (MM/DD/YYYY)?")
                
                # Get activities for the trip
                dest_info['activity'] = ask_user_question(f"Are there any specific activities you are looking for in {destination}, {country}?")
                
                # Get food preferences for the trip
                dest_info['food'] = ask_user_question(f"Are there any specific types of food you are looking for in {destination}, {country}?")
                
                # Save responses to database
                save_destination_preferences(db_path, country, destination, dest_info)

    if not args.skip_research:
        # Start asking destination-specific questions
        for country in countries:
            for destination in destinations[country]:
                
                dest_info = load_destination_preferences(db_path, country, destination)
                
                # Prompt Gemini for recommendations/suggestions for the trip - factoring in user's general and destination-specific preferences
                cntr = 0
                for prompt_type in prompt_types:
                    curr_prompt = instructions[prompt_type].format(destination=destination, country=country)
                    with console.status(f"[green]Getting {prompt_type} info for {destination}, {country}...", spinner="earth"):
                        list_obj = get_destination_specific_info(destination, country, curr_prompt, gen_info, dest_info, prompt_type)
                        for item in list_obj.items:
                            # Set the type attribute based on the current prompt_type
                            item.type = prompt_type
                            console.print(f"[yellow]Looking for {item.proper_title} in {country} {destination}...")
                            #item_embedding = generate_embedding(f"{country} {destination} {item.proper_title}", EMBEDDING_MODEL_NAME, os.environ["GEMINI_API_KEY"])
                            item_embedding = None
                            if item.is_specific_location:
                                console.print(f"[green]Generated text embedding.... Searching for existing entry...")
                                retrieved_item = search_data_for_item(console, data, country, destination, item)
                                if not retrieved_item:
                                    console.print(f"[red]No match found above theshold 0.93 - Getting from Google Maps...")
                                    try:
                                        api_responses = get_place_details(gmaps, item.proper_title, destination)
                                        console.print(f"[green]Got Google Maps data: ")
                                    except ValueError:
                                        console.print(f"[red]Failed. Could not find on Google Maps...")
                                    data.append((item_embedding, country, destination, item, api_responses))
                                else:
                                    console.print(f"[green]Found similar entry: {retrieved_item[3].proper_title}! (vs {item.proper_title}...)")
                            else:
                                data.append((item_embedding, country, destination, item, {}))
                            cntr += 1
                    save_data_to_db(db_path, data)
                
                if MODEL_NAME == "gemini-1.5-pro":       
                    with console.status(f"[orange]Waiting 30 seconds to avoid Gemini rate limit on Pro API...", spinner="dots"):
                        time.sleep(15)
    load_interface(data, prompt_types)  

    console.print("[green]All Done!")

if __name__ == "__main__":
    main()



