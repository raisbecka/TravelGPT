import datetime
import pytz
from datetime import datetime as dt, timedelta
from datetime import timezone as tz
import sys
import json
import os
import time
import subprocess
import gradio as gr
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time
from libraries.data import Item
import plotly.graph_objects as go
from rich.console import Console
import asyncio
from tools import cluster_locations, calculate_location_route


def create_interface(data, prompt_types):
    # Get unique destinations
    destinations = list(set(item[2] for item in data))
    
    # Define trip dates for each destination
    trip_dates = {
        dest: {
            "start": dt.now().strftime("%Y-%m-%d"),
            "end": dt.now().strftime("%Y-%m-%d"),
            "days": 0
        } for dest in destinations
    }
    
    def update_trip_dates(field_name, ctrl_date, type_selector, destination):
        
        # Initialize a global variable to store the last update timestamp
        if not hasattr(update_trip_dates, 'last_update'):
            update_trip_dates.last_update = int(time.time())
        else:
            
            # Get the current timestamp in seconds
            current_time = int(time.time())

            # Check if at least 2 seconds has passed since the last update
            if current_time - update_trip_dates.last_update < 2:
                return ctrl_date

            # Update the last update timestamp
            update_trip_dates.last_update = current_time
        
        # Fix STUPID FUCKING timezone issue. FFS Gradio devs
        print(ctrl_date)
        ctrl_date = dt.fromtimestamp(int(ctrl_date)) + timedelta(hours=24)
        ctrl_date = ctrl_date.strftime("%Y-%m-%d")
        trip_dates[destination][field_name] = ctrl_date
        
        # Set days between start and end date
        start_date = dt.strptime(trip_dates[destination]["start"], "%Y-%m-%d")
        end_date = dt.strptime(trip_dates[destination]["end"], "%Y-%m-%d")
        trip_dates[destination]["days"] = (end_date - start_date).days

        return ctrl_date

    def update_map(selected_type, destination, *checkboxes):
        visible_items = [item for item, checked in zip(data, checkboxes) if checked and item[3].type == selected_type and item[2] == destination]
        lat = [item[4]['geocode']['geometry']['location']['lat'] for item in visible_items]
        lon = [item[4]['geocode']['geometry']['location']['lng'] for item in visible_items]
        text = [item[3].proper_title for item in visible_items]

        fig = go.Figure(go.Scattermapbox(
            lat=lat,
            lon=lon,
            mode='markers',
            marker=go.scattermapbox.Marker(size=10),
            text=text,
            hoverinfo='text'
        ))

        fig.update_layout(
            mapbox_style="outdoors",
            mapbox=dict(
                accesstoken=os.environ.get('MAPBOX_ACCESS_TOKEN'),
                center={'lat': sum(lat)/len(lat) if lat else 35.6762, 'lon': sum(lon)/len(lon) if lon else 139.6503},
                zoom=10
            ),
            showlegend=False,
            height=600,
            margin={"r":0,"t":0,"l":0,"b":0}
        )

        return fig

    def filter_checkboxes(selected_type, destination):
        return [gr.update(visible=item[3].type == selected_type and item[2] == destination) for item in data]

    
    def process_itinerary(selections):
        
        # Create selected_data list
        selected_data = []
        for prompt_type, indexes in selections.items():
            if prompt_type != "days":
                selected_data.extend([data[i] for i in indexes])
        
        num_clusters = selections["days"]

        # Call cluster_locations
        clustered_data = cluster_locations(selected_data, num_clusters)

        # Call calculate_location_route
        processed_data = calculate_location_route(clustered_data)
        
        print(processed_data)

        return processed_data
    

    def generate_itinerary():
        # Show loading overlay
        yield gr.update(visible=True), gr.update(visible=True)
        
        # Make selected data json
        selections = {prompt_type: [] for prompt_type in prompt_types}
        for i, (checked, item) in enumerate(zip(checkboxes, data)):
            if checked and item[2] == destination:
                selections[item[3].type].append(i)
        selections["days"] = trip_dates[destination]["days"]
        
        print(selections["days"])

        process_itinerary(selections)

        # Hide loading overlay and show itinerary tab
        yield gr.update(visible=False), gr.update(selected="Itinerary")

        # TODO: Update the itinerary display with processed_data
        # This part will depend on how you want to display the itinerary

    with gr.Blocks(theme=gr.themes.Soft(), css=".block{overflow-y: hidden !important;} .time{min-width: 50px !important;}") as demo:
        gr.Markdown("# Giga-Planner 5000")
        
        with gr.Tabs() as tabs:
            for destination in destinations:
                with gr.Tab(destination):
                    dest_val = gr.Textbox(value=destination, visible=False)
                    
                    # New inner tabs
                    with gr.Tabs() as inner_tabs:
                        with gr.Tab("Planner"):
                            # Everything that was previously here
                            with gr.Row():
                                type_selector = gr.Radio(
                                    choices=prompt_types,
                                    show_label=False,
                                    value=prompt_types[0],
                                    interactive=True
                                )

                            with gr.Row():
                                with gr.Column(scale=1):
                                    with gr.Accordion("Destination Dates", open=False):
                                        with gr.Row():
                                            start_date = gr.DateTime(label="Start Date", min_width=50, include_time=False, value=trip_dates[destination]["start"], timezone="US/Eastern")
                                            end_date = gr.DateTime(label="End Date", min_width=50, include_time=False, value=trip_dates[destination]["end"], timezone="US/Eastern")
                                    with gr.Group():
                                        gr.Markdown(" <b>Item List</b>")
                                        checkboxes = [gr.Checkbox(label=item[3].item_title, value=True, visible=item[3].type == prompt_types[0] and item[2] == destination) for item in data]
                                
                                with gr.Column(scale=2):
                                    map_component = gr.Plot()

                            with gr.Row():
                                save_btn = gr.Button("Generate Itinerary")
                                cancel_btn = gr.Button("Cancel")

                            # Hidden JSON component to store selections
                            selections = gr.JSON(visible=True)
                            
                            # Handle tab changes
                            tabs.change(update_map, inputs=[type_selector, dest_val] + checkboxes, outputs=map_component)

                            # Update map when type is changed or checkboxes are toggled
                            type_selector.change(update_map, inputs=[type_selector, dest_val] + checkboxes, outputs=map_component)
                            type_selector.change(filter_checkboxes, inputs=[type_selector, dest_val], outputs=checkboxes)
                            
                            start_date.change(update_trip_dates, inputs=[gr.Textbox(value="start", visible=False),start_date, type_selector, dest_val], outputs=[start_date])
                            end_date.change(update_trip_dates, inputs=[gr.Textbox(value="end", visible=False),end_date, type_selector, dest_val], outputs=[end_date])
                            
                            for checkbox in checkboxes:
                                checkbox.change(update_map, inputs=[type_selector, dest_val] + checkboxes, outputs=map_component)

                            # Handle save and cancel actions
                            save_btn.click(
                                fn=generate_itinerary,
                                inputs=[],
                                outputs=[
                                    gr.Markdown(value="Loading...", visible=False),  
                                    inner_tabs  # To update tab visibility and selection
                                ]
                            )
                            cancel_btn.click(lambda: None, outputs=selections)
                            
                            # Load initial map
                            demo.load(update_map, inputs=[type_selector, gr.Textbox(value=destination, visible=False)] + checkboxes, outputs=map_component)

                        with gr.Tab("Itinerary", visible=False):
                            # Placeholder for the itinerary display
                            itinerary_display = gr.Markdown("Itinerary will be displayed here")

    return demo


def load_interface(data, prompt_types):
    
    demo = create_interface(data, prompt_types)
    
    # Create and launch interface
    result = demo.launch()

    # Wait for the interface thread to complete
    return json.loads(result) if result else None

# Example usage:
if __name__ == "__main__":
    
    c = Console()

    class InterfaceReloader(FileSystemEventHandler):
        def __init__(self):
            self.process = None

        def on_modified(self, event):
            if event.src_path.endswith('interface.py'):
                c.print("[yellow]Change detected. Reloading...[/yellow]")
                if self.process:
                    self.process.terminate()
                    self.process.wait()
                self.process = subprocess.Popen(['py', '-3.9', 'interface.py'])

    def run_with_reloader():
        reloader = InterfaceReloader()
        reloader.process = subprocess.Popen(['py', '-3.9', 'interface.py'])

        observer = Observer()
        observer.schedule(reloader, path='.', recursive=False)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()

        if reloader.process:
            reloader.process.terminate()
            reloader.process.wait()
            
    if os.environ.get('WATCHDOG_RELOADER') != 'true':
        os.environ['WATCHDOG_RELOADER'] = 'true'
        run_with_reloader()
        sys.exit(0)
    
    # Updated mock data for testing
    data = [
        (None, "Japan", "Tokyo", Item(proper_title="Tokyo Tower", type="activity", item_title="Visit Tokyo Tower", description="Iconic communications and observation tower", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6586, "lng": 139.7454}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Sensoji Temple", type="activity", item_title="Explore Sensoji Temple", description="Ancient Buddhist temple in Asakusa", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.7147, "lng": 139.7967}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Ueno Park", type="activity", item_title="Stroll through Ueno Park", description="Large public park with museums and zoo", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.7154, "lng": 139.7731}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="teamLab Borderless", type="activity", item_title="Experience teamLab Borderless", description="Digital art museum with immersive installations", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6248, "lng": 139.7767}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Sushi Dai", type="food", item_title="Dine at Sushi Dai", description="Famous sushi restaurant in Toyosu Fish Market", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6654, "lng": 139.7707}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Ichiran Ramen", type="food", item_title="Try Ichiran Ramen", description="Popular ramen chain known for tonkotsu ramen", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6595, "lng": 139.7005}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Tsukiji Outer Market", type="food", item_title="Explore Tsukiji Outer Market", description="Vibrant market with fresh seafood and street food", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6654, "lng": 139.7707}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Gonpachi Nishi-Azabu", type="food", item_title="Visit Gonpachi Nishi-Azabu", description="Inspiration for the Kill Bill restaurant scene", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6598, "lng": 139.7273}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Park Hyatt Tokyo", type="accommodation", item_title="Stay at Park Hyatt Tokyo", description="Luxury hotel featured in Lost in Translation", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6866, "lng": 139.6907}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Capsule Hotel Anshin Oyado", type="accommodation", item_title="Experience Capsule Hotel Anshin Oyado", description="Modern capsule hotel with amenities", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6938, "lng": 139.7034}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Ryokan Sawanoya", type="accommodation", item_title="Stay at Ryokan Sawanoya", description="Traditional Japanese inn in Yanaka", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.7277, "lng": 139.7662}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Trunk Hotel", type="accommodation", item_title="Book Trunk Hotel", description="Stylish boutique hotel in Shibuya", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.6614, "lng": 139.7040}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Kamakura", type="day trip", item_title="Day trip to Kamakura", description="Coastal town with Great Buddha statue", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.3192, "lng": 139.5467}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Hakone", type="day trip", item_title="Explore Hakone", description="Hot springs and views of Mount Fuji", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.2323, "lng": 139.1069}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Nikko", type="day trip", item_title="Visit Nikko", description="UNESCO World Heritage site with shrines and temples", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 36.7439, "lng": 139.5856}}}}),
        (None, "Japan", "Tokyo", Item(proper_title="Yokohama", type="day trip", item_title="Discover Yokohama", description="Port city with Minato Mirai 21 district", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.4437, "lng": 139.6380}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Kiyomizu-dera", type="activity", item_title="Visit Kiyomizu-dera", description="Famous Buddhist temple with wooden terrace", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.9948, "lng": 135.7850}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Fushimi Inari Taisha", type="activity", item_title="Explore Fushimi Inari Taisha", description="Shinto shrine with thousands of torii gates", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.9671, "lng": 135.7727}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Arashiyama Bamboo Grove", type="activity", item_title="Stroll through Arashiyama Bamboo Grove", description="Iconic bamboo forest path", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0170, "lng": 135.6710}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Nijo Castle", type="activity", item_title="Experience Nijo Castle", description="UNESCO World Heritage site with nightingale floors", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0142, "lng": 135.7480}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Nishiki Market", type="food", item_title="Explore Nishiki Market", description="Lively food market with local specialties", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0048, "lng": 135.7649}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Ippudo Ramen", type="food", item_title="Try Ippudo Ramen", description="Popular ramen chain with Kyoto-style dishes", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0116, "lng": 135.7681}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Gion Karyo", type="food", item_title="Dine at Gion Karyo", description="Traditional Kyoto cuisine in historic Gion district", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0056, "lng": 135.7746}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Kyoto Gogyo", type="food", item_title="Visit Kyoto Gogyo", description="Known for unique burnt miso ramen", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0031, "lng": 135.7714}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="The Ritz-Carlton Kyoto", type="accommodation", item_title="Stay at The Ritz-Carlton Kyoto", description="Luxury hotel overlooking the Kamogawa River", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0157, "lng": 135.7682}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="9 Hours Kyoto", type="accommodation", item_title="Experience 9 Hours Kyoto", description="Modern capsule hotel near Kyoto Station", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.9871, "lng": 135.7585}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Ryokan Yoshida-sanso", type="accommodation", item_title="Stay at Ryokan Yoshida-sanso", description="Traditional Japanese inn with garden views", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.0269, "lng": 135.7868}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Hotel Kanra Kyoto", type="accommodation", item_title="Book Hotel Kanra Kyoto", description="Boutique hotel blending modern and traditional design", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.9896, "lng": 135.7624}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Nara", type="day trip", item_title="Day trip to Nara", description="Ancient capital with friendly deer and temples", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.6851, "lng": 135.8048}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Uji", type="day trip", item_title="Explore Uji", description="Famous for green tea and Byodoin Temple", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.8892, "lng": 135.8029}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Kurama", type="day trip", item_title="Visit Kurama", description="Mountain village with hot springs and temples", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 35.1139, "lng": 135.7708}}}}),
        (None, "Japan", "Kyoto", Item(proper_title="Osaka", type="day trip", item_title="Discover Osaka", description="Vibrant city known for food and nightlife", is_specific_location=True), {"geocode": {"geometry": {"location": {"lat": 34.6937, "lng": 135.5023}}}}),
    ]
    prompt_types = ["activity", "food", "accommodation", "day trip"]
    
    result = load_interface(data, prompt_types)
    print(result)