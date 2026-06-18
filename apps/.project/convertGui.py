# GIS Batch Converter Tool - Auto-detect Format & Save Preferences
import os
import sys

# Fix: Resolve PROJ database version mismatch (common with PostgreSQL/PostGIS installations)
try:
    import pyproj
    proj_path = pyproj.datadir.get_data_dir()
    os.environ['PROJ_LIB'] = proj_path
    os.environ['PROJ_DATA'] = proj_path
except Exception:
    # If pyproj isn't installed or data dir isn't found, at least clear the conflicting variables
    if 'PROJ_LIB' in os.environ: del os.environ['PROJ_LIB']
    if 'PROJ_DATA' in os.environ: del os.environ['PROJ_DATA']

import json
from tkinter import ttk, messagebox
from tkinter.filedialog import askdirectory
import tkinter as tk

from batchconvert import batch_convert

# Configuration file path
CONFIG_FILE = 'conversion_config.json'

class ConvertGui:
    def __init__(self):
        # Dictionary of formats to convert to and from with their file extension
        self.driver_options_dict = {
            'DXF': '.dxf', 'CSV': '.csv', 'OpenFileGDB': '.gdb',  'ESRIJSON': '.json', 'ESRI Shapefile': '.shp', 
            'FlatGeobuf': '.fgb', 'GeoJSON': '.geojson', 'GeoJSONSeq': '.geojsons', 'GPKG': '.gpkg', 'GML': '.gml',
            'OGR_GMT': '.GMT', 'GPX': '.gpx', 'Idrisi': '.rst', 'MapInfo File': '.tab',
            'DGN': '.dgn', 'PCIDSK': '.pix',  'S57': '.000', 'SQLite': '.sqlite', 'TopoJSON': '.topojson',
            'KML': '.kml', 'KMZ': '.kmz', 'GeoParquet': '.parquet', 'Avro': '.avro', 'Arrow IPC': '.arrow', 'GeoTIFF': '.tif',
            'GTiff': '.tif', 'PNG': '.png', 'JPEG': '.jpg', 'JPG': '.jpg'
        }
        # Raster formats that need special handling via rasterio
        self.raster_formats = {'GTiff': '.tif', 'PNG': '.png', 'JPEG': '.jpg', 'JPG': '.jpg'}
        # Reverse mapping: extension to format name
        self.ext_to_driver = {v.lower(): k for k, v in self.driver_options_dict.items()}
        
        self.driver_options = list(self.driver_options_dict.keys())

        self.crs_options_dict = {
            'ETRS89 / UTM Zone 32N (Europe) - EPSG: 25832': '25832',
            'OSGB36 (OSGB 1936) - EPSG: 27700': '27700',
            'TM65 / Irish Grid - EPSG: 29902': '29902',
            'WGS 84 / UTM Zone 33N - EPSG: 32633': '32633',
            'WGS 84 / UTM Zone 36S - EPSG: 32736': '32736',
            'WGS 84 / Pseudo-Mercator - EPSG: 3857': '3857',
            'ETRS89 / Europe - EPSG: 4258': '4258',
            'NAD83 (North American Datum 1983) - EPSG: 4269': '4269',
            'WGS 84 (Global GPS Coordinate System) - EPSG: 4326': '4326'
        }
        
        self.crs_options = list(self.crs_options_dict.keys())
        self.conversion_crs = ''
        self.input_path = None
        self.output_path = None
        self.detected_format = None

        # Load saved preferences
        self.load_config()

        # Known file descriptions from documentation (PROJECT_OVERVIEW.md)
        self.known_file_descriptions = {
            'sample_locations.csv': "Contains 10 geographic locations with Latitude/longitude coordinates and Address information. Perfect for testing coordinate conversion.",
            'buildings_data.csv': "Contains 10 buildings with attributes including Area, type, construction year, and Occupancy rates. Good for testing data field conversions.",
            'regions_data.csv': "Regional geographic data including Population, elevation, and Area measurements. Useful for testing aggregation and regional analysis."
        }

        # Format descriptions
        self.format_descriptions = {
            '.shp': "ESRI Shapefile: A popular geospatial vector data format for geographic information system (GIS) software.",
            '.geojson': "GeoJSON: An open standard format designed for representing simple geographical features, along with their non-spatial attributes.",
            '.csv': "CSV (Comma Separated Values): Often used in GIS to store point data using latitude and longitude columns.",
            '.gpkg': "GeoPackage: An open, non-proprietary, platform-independent and standards-based data format for geographic information.",
            '.fgb': "FlatGeobuf: An efficient binary encoding for geographic features that supports spatial indexing.",
            '.tif': "GeoTIFF: A public domain metadata standard which allows georeferencing information to be embedded within a TIFF file.",
            '.tiff': "GeoTIFF: A public domain metadata standard which allows georeferencing information to be embedded within a TIFF file.",
            '.png': "PNG (Portable Network Graphics): A raster graphics file format that supports lossless data compression.",
            '.jpg': "JPEG: A commonly used method of lossy compression for digital images, particularly for those images produced by digital photography.",
            '.jpeg': "JPEG: A commonly used method of lossy compression for digital images."
        }

        # GUI main window
        self.main_window = tk.Tk()
        self.init_settings_vars()
        self.conversion_ui()

    def init_settings_vars(self):
        """Initialize Tk variables for the settings sidebar."""
        self.auto_detect_var = tk.BooleanVar(value=self.config.get('auto_detect_format', True))
        self.save_preferences_var = tk.BooleanVar(value=self.config.get('save_preferences', True))
        self.default_output_var = tk.StringVar(value=self.config.get('default_output_format') or self.config.get('last_convert_to') or '')
        self.default_crs_var = tk.StringVar(value=self.config.get('default_crs') or self.config.get('last_crs') or '')

    def load_config(self):
        """Load saved conversion preferences from config file"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    self.config = json.load(f)
            except:
                self.config = {}
        else:
            self.config = {}

    def save_config(self):
        """Save conversion preferences to config file"""
        self.config['auto_detect_format'] = self.auto_detect_var.get()
        self.config['save_preferences'] = self.save_preferences_var.get()
        self.config['default_output_format'] = self.default_output_var.get() or None
        self.config['default_crs'] = self.default_crs_var.get() or None

        if self.save_preferences_var.get():
            self.config['last_convert_from'] = self.input_driver if hasattr(self, 'input_driver') else None
            self.config['last_convert_to'] = self.conversion_driver if hasattr(self, 'conversion_driver') else None
            self.config['last_crs'] = self.conversion_crs if self.conversion_crs else None
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)
        print(f"Configuration saved to {CONFIG_FILE}")

    def detect_input_format(self):
        """Auto-detect input file format by scanning files in the input directory"""
        if not self.input_path or not os.path.isdir(self.input_path):
            return None
        
        for file_name in os.listdir(self.input_path):
            full_path = os.path.join(self.input_path, file_name)
            if os.path.isfile(full_path):
                file_ext = os.path.splitext(file_name)[1].lower()
                if file_ext in self.ext_to_driver:
                    return self.ext_to_driver[file_ext]
        
        return None

    def set_default_crs_combo(self):
        """Select the CRS display label that matches the saved EPSG value."""
        saved_crs = self.default_crs_var.get()
        if not saved_crs:
            return

        for label, epsg in self.crs_options_dict.items():
            if epsg == saved_crs or label == saved_crs:
                self.default_crs_combo.set(label)
                self.default_crs_var.set(epsg)
                return

    def apply_settings(self):
        """Apply sidebar defaults to the main conversion controls."""
        if self.default_output_var.get():
            self.combo_convert.set(self.default_output_var.get())

        crs_choice = self.default_crs_combo.get()
        if crs_choice:
            self.combo_crs.set(crs_choice)
            self.default_crs_var.set(self.crs_options_dict.get(crs_choice, crs_choice))

        if self.auto_detect_var.get() and self.input_path:
            self.detected_format = self.detect_input_format()
            if self.detected_format:
                self.combo_input.set(self.detected_format)

        self.update_settings_summary()
        self.status_label.config(text='Settings applied', foreground='green')

    def save_settings_only(self):
        """Save sidebar settings without requiring a conversion run."""
        crs_choice = self.default_crs_combo.get()
        self.default_crs_var.set(self.crs_options_dict.get(crs_choice, '') if crs_choice else '')
        self.save_config()
        self.update_settings_summary()
        self.status_label.config(text='Settings saved', foreground='green')

    def reset_settings(self):
        """Reset sidebar settings to their default values."""
        self.auto_detect_var.set(True)
        self.save_preferences_var.set(True)
        self.default_output_var.set('')
        self.default_crs_var.set('')
        self.default_crs_combo.set('')
        self.combo_convert.set('')
        self.combo_crs.set('')
        self.update_settings_summary()
        self.status_label.config(text='Settings reset. Click Save Settings to keep this reset.', foreground='orange')

    def update_settings_summary(self):
        """Refresh the sidebar summary text."""
        output_format = self.default_output_var.get() or 'Not set'
        crs_choice = self.default_crs_combo.get()
        crs_value = self.crs_options_dict.get(crs_choice) if crs_choice else self.default_crs_var.get()
        crs_text = crs_value or 'Not set'
        detect_text = 'On' if self.auto_detect_var.get() else 'Off'
        save_text = 'On' if self.save_preferences_var.get() else 'Off'
        self.settings_summary_label.config(
            text=(
                f"Default output: {output_format}\n"
                f"Default CRS: {crs_text}\n"
                f"Auto-detect: {detect_text}\n"
                f"Save preferences: {save_text}"
            )
        )

        # main window UI of tkinter for conversion tool
    def conversion_ui(self):
        self.main_window.config(width=1280, height=680)
        self.main_window.title('GIS File Conversion - Auto Detect Format, Settings & Search')
        self.main_window.resizable(False, False)
        self.apply_ui_style()

        # ===== INPUT DIRECTORY SECTION =====
        input_frame = ttk.LabelFrame(self.main_window, text="Input Directory", padding=10)
        input_frame.place(x=20, y=20, width=500, height=120)

        self.input_button = ttk.Button(input_frame, text='Select Input Directory', command=self.select_input_directory)
        self.input_button.pack(pady=5)
        
        self.input_path_label = ttk.Label(input_frame, text='No input directory selected', wraplength=480)
        self.input_path_label.pack(pady=5)

        # Auto-detected format display
        detected_frame = ttk.Frame(input_frame)
        detected_frame.pack()
        detected_label = ttk.Label(detected_frame, text='Detected Format: ', font=('Arial', 9, 'bold'))
        detected_label.pack(side='left')
        self.detected_format_label = ttk.Label(detected_frame, text='None', foreground='blue', font=('Arial', 10))
        self.detected_format_label.pack(side='left')

        # ===== OUTPUT DIRECTORY SECTION =====
        output_frame = ttk.LabelFrame(self.main_window, text="Output Directory", padding=10)
        output_frame.place(x=20, y=150, width=500, height=120)

        self.output_button = ttk.Button(output_frame, text='Select Output Directory', command=self.select_output_directory)
        self.output_button.pack(pady=5)
        
        self.output_path_label = ttk.Label(output_frame, text='No output directory selected', wraplength=480)
        self.output_path_label.pack(pady=5)

        # ===== FORMAT CONVERSION SECTION =====
        format_frame = ttk.LabelFrame(self.main_window, text="Conversion Settings", padding=10)
        format_frame.place(x=20, y=280, width=500, height=150)

        # Convert FROM (Auto-detected)
        convert_from_label = ttk.Label(format_frame, text="Convert From (Auto-Detected):", font=('Arial', 9, 'bold'))
        convert_from_label.grid(row=0, column=0, sticky='w', pady=5)
        self.combo_input = ttk.Combobox(format_frame, state="readonly", values=self.driver_options, width=25)
        self.combo_input.grid(row=0, column=1, padx=10, pady=5)

        # Convert TO (Manual selection)
        convert_to_label = ttk.Label(format_frame, text="Convert To (Select Format):", font=('Arial', 9, 'bold'))
        convert_to_label.grid(row=1, column=0, sticky='w', pady=5)
        self.combo_convert = ttk.Combobox(format_frame, state='readonly', values=self.driver_options, width=25)
        self.combo_convert.grid(row=1, column=1, padx=10, pady=5)

        # Load last conversion format if available
        preferred_output = self.default_output_var.get() or self.config.get('last_convert_to')
        if preferred_output:
            self.combo_convert.set(preferred_output)

        # CRS conversion
        crs_label = ttk.Label(format_frame, text='Output CRS (Coordinate System):', font=('Arial', 9, 'bold'))
        crs_label.grid(row=2, column=0, sticky='w', pady=5)
        self.combo_crs = ttk.Combobox(format_frame, state='readonly', values=self.crs_options, width=25)
        self.combo_crs.grid(row=2, column=1, padx=10, pady=5)

        # Load last CRS if available
        preferred_crs = self.default_crs_var.get() or self.config.get('last_crs')
        if preferred_crs:
            # Find the key for this CRS value
            for key, value in self.crs_options_dict.items():
                if value == preferred_crs:
                    self.combo_crs.set(key)
                    break

        # ===== SUBMISSION SECTION =====
        button_frame = ttk.Frame(self.main_window)
        button_frame.place(x=20, y=440, width=500, height=80)

        submit_label = ttk.Label(button_frame, text="Configure settings above and click Submit to start conversion", 
                                font=('Arial', 10, 'italic'))
        submit_label.pack(pady=5)

        self.submit_button = ttk.Button(button_frame, text="▶ START CONVERSION", command=self.submit_selection)
        self.submit_button.pack(pady=5, ipadx=20, ipady=10)

        # ===== STATUS SECTION =====
        status_frame = ttk.LabelFrame(self.main_window, text="Status", padding=10)
        status_frame.place(x=20, y=530, width=500, height=130)

        self.status_label = ttk.Label(status_frame, text='Ready to convert files', 
                                     font=('Arial', 9), foreground='green')
        self.status_label.pack(pady=5)

        self.details_label = ttk.Label(status_frame, text='', wraplength=480, justify='left')
        self.details_label.pack(pady=5)

        # ===== SETTINGS SIDEBAR =====
        settings_frame = ttk.LabelFrame(self.main_window, text="Settings", padding=12, style='Sidebar.TLabelframe')
        settings_frame.place(x=540, y=20, width=300, height=640)

        ttk.Label(settings_frame, text="Defaults", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 8))

        ttk.Label(settings_frame, text="Default output format:").pack(anchor='w')
        self.default_output_combo = ttk.Combobox(
            settings_frame,
            state='readonly',
            values=self.driver_options,
            textvariable=self.default_output_var,
            width=27
        )
        self.default_output_combo.pack(anchor='w', fill='x', pady=(2, 12))

        ttk.Label(settings_frame, text="Default output CRS:").pack(anchor='w')
        self.default_crs_combo = ttk.Combobox(
            settings_frame,
            state='readonly',
            values=self.crs_options,
            width=27
        )
        self.default_crs_combo.pack(anchor='w', fill='x', pady=(2, 12))
        self.set_default_crs_combo()

        ttk.Separator(settings_frame).pack(fill='x', pady=12)

        ttk.Label(settings_frame, text="Behavior", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 8))
        self.auto_detect_check = ttk.Checkbutton(
            settings_frame,
            text="Auto-detect input format",
            variable=self.auto_detect_var
        )
        self.auto_detect_check.pack(anchor='w', pady=4)

        self.save_preferences_check = ttk.Checkbutton(
            settings_frame,
            text="Save preferences",
            variable=self.save_preferences_var
        )
        self.save_preferences_check.pack(anchor='w', pady=4)

        ttk.Separator(settings_frame).pack(fill='x', pady=12)

        ttk.Label(settings_frame, text="Current Session", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(0, 8))
        self.settings_summary_label = ttk.Label(settings_frame, text='', wraplength=270, justify='left')
        self.settings_summary_label.pack(anchor='w', fill='x', pady=(0, 12))

        ttk.Button(settings_frame, text="Apply Settings", command=self.apply_settings, style='SidebarAction.TButton').pack(fill='x', pady=4, ipady=2)
        ttk.Button(settings_frame, text="Save Settings", command=self.save_settings_only).pack(fill='x', pady=4)
        ttk.Button(settings_frame, text="Reset Settings", command=self.reset_settings).pack(fill='x', pady=4)
        ttk.Button(settings_frame, text="Refresh File View", command=self.refresh_directory_display).pack(fill='x', pady=4)

        self.update_settings_summary()
        
        # ===== FILE SEARCH SECTION (RIGHT SIDE) =====
        search_frame = ttk.LabelFrame(self.main_window, text="Search File Details (Input & Output)", padding=10)
        search_frame.place(x=860, y=20, width=400, height=640)

        search_label = ttk.Label(search_frame, text="Search files by typing keywords:", font=('Arial', 9, 'bold'))
        search_label.pack(anchor='w', padx=5, pady=5)

        search_input_frame = ttk.Frame(search_frame)
        search_input_frame.pack(anchor='w', padx=5, pady=5, fill='x')

        self.search_entry = ttk.Entry(search_input_frame)
        self.search_entry.pack(side='left', padx=5, fill='x', expand=True)
        self.search_entry.bind('<Return>', lambda e: self.search_files())

        self.search_button = ttk.Button(search_input_frame, text="🔍 Search", command=self.search_files)
        self.search_button.pack(side='left', padx=5)

        # Results display area
        results_frame = ttk.Frame(search_frame)
        results_frame.pack(padx=5, pady=5, fill='both', expand=True)
        
        self.search_results_text = tk.Text(results_frame, wrap='word', bg='white', fg='black')
        self.search_results_text.pack(side='left', fill='both', expand=True)

        scrollbar = ttk.Scrollbar(results_frame, orient='vertical', command=self.search_results_text.yview)
        scrollbar.pack(side='right', fill='y')
        self.search_results_text['yscrollcommand'] = scrollbar.set

    def apply_ui_style(self):
        """Apply a cleaner, modern-light style for key controls."""
        style = ttk.Style(self.main_window)
        try:
            style.theme_use('clam')
        except Exception:
            pass

        style.configure('Sidebar.TLabelframe', padding=10)
        style.configure('Sidebar.TLabelframe.Label', font=('Arial', 10, 'bold'))
        style.configure('SidebarAction.TButton', font=('Arial', 9, 'bold'))
        

    def select_input_directory(self):
        """Select input directory and auto-detect format from files inside it"""
        selected_dir = askdirectory(title='Select Input Directory containing GIS Files')
        
        if selected_dir:
            self.input_path = selected_dir
            self.input_path_label.config(text=self.input_path)
            
            # Display all files and folders in the results area
            self.refresh_directory_display()

            if not self.auto_detect_var.get():
                self.detected_format_label.config(text='Auto-detect off', foreground='orange')
                self.status_label.config(text='Input directory selected. Choose input format manually.', foreground='green')
                self.update_settings_summary()
                return
            
            # Auto-detect format from files in the directory
            self.detected_format = self.detect_input_format()
            
            if self.detected_format:
                # Count how many files match this format
                ext = self.driver_options_dict.get(self.detected_format, '').lower()
                count = sum(1 for f in os.listdir(self.input_path)
                            if os.path.isfile(os.path.join(self.input_path, f))
                            and os.path.splitext(f)[1].lower() == ext)
                self.detected_format_label.config(
                    text=f'{self.detected_format} ({count} files)', foreground='green')
                self.combo_input.set(self.detected_format)
                self.status_label.config(text=f'✓ Format detected: {self.detected_format} — {count} file(s) found', foreground='green')
            else:
                self.detected_format_label.config(text='Unknown - Select manually', foreground='red')
                self.status_label.config(text='✗ Could not detect format. Please select manually.', foreground='red')

    def refresh_directory_display(self):
        """Refresh the search results area with contents of input and output directories"""
        self.search_results_text.config(state='normal')
        self.search_results_text.delete('1.0', 'end')
        
        def get_dir_text(path, title):
            if not path or not os.path.isdir(path):
                return ""
            
            try:
                items = os.listdir(path)
                files = [i for i in items if os.path.isfile(os.path.join(path, i))]
                folders = [i for i in items if os.path.isdir(os.path.join(path, i))]
                
                text = f"--- {title} DIRECTORY: {path} ---\n"
                text += f"Folders: {len(folders)} | Files: {len(files)}\n"
                text += f"{'='*60}\n"
                
                # List folders first
                for folder in sorted(folders):
                    text += f"📁 [FOLDER] {folder}\n"
                
                # List files
                for file in sorted(files):
                    file_path = os.path.join(path, file)
                    size = os.path.getsize(file_path)
                    ext = os.path.splitext(file)[1].upper()
                    text += f"📄 {file} | {ext if ext else 'FILE'} | {size} bytes\n"
                text += "\n"
                return text
            except Exception as e:
                return f"Error reading {title} directory: {str(e)}\n\n"

        full_text = ""
        if self.input_path:
            full_text += get_dir_text(self.input_path, "INPUT")
        if self.output_path:
            full_text += get_dir_text(self.output_path, "OUTPUT")
            
        if not full_text:
            full_text = "No directories selected yet. Select a directory to see its contents here."
            
        self.search_results_text.insert('1.0', full_text)
        self.search_results_text.config(state='disabled')

    def select_output_directory(self):
        """Select output directory"""
        selected_dir = askdirectory(title="Select Output Directory for Converted Files")
        
        if selected_dir:
            self.output_path = selected_dir
            self.output_path_label.config(text=self.output_path)
            
            # Refresh display to show output directory contents too
            self.refresh_directory_display()
            self.status_label.config(text='✓ Output directory selected', foreground='green')


    def submit_selection(self):
        """Start conversion process"""
        # Validate selections
        if not self.input_path:
            messagebox.showerror('Error', 'Please select an Input Directory')
            return
        
        if not self.output_path:
            messagebox.showerror('Error', 'Please select an Output Directory')
            return
        
        if not self.combo_input.get():
            messagebox.showerror('Error', 'Please select Convert From format')
            return
        
        if not self.combo_convert.get():
            messagebox.showerror('Error', 'Please select Convert To format')
            return

        # Get conversion settings
        self.conversion_driver = self.combo_convert.get()
        self.conversion_driver_ext = self.driver_options_dict.get(self.conversion_driver)
        self.input_driver = self.combo_input.get()
        self.input_driver_ext = self.driver_options_dict.get(self.input_driver)
        self.conversion_choice = self.combo_crs.get()
        self.conversion_crs = self.crs_options_dict.get(self.conversion_choice) if self.conversion_choice else None

        # Prepare conversion details
        details = f"Converting from: {self.input_driver}\nConverting to: {self.conversion_driver}\n"
        if self.conversion_crs:
            details += f"Output CRS: {self.conversion_choice}"
        
        self.details_label.config(text=details)

        # Confirmation dialog
        message = f"Ready to convert!\n\nFrom: {self.input_driver}\nTo: {self.conversion_driver}\nInput: {self.input_path}\nOutput: {self.output_path}"
        confirm = messagebox.askyesno(title='Confirm Conversion', message=message)
        
        if confirm:
            try:
                self.status_label.config(text='⏳ Converting files...', foreground='orange')
                self.main_window.update()
                
                # Print conversion info to console
                print("\n" + "="*60)
                print("CONVERSION STARTED")
                print("="*60)
                print(f"Input Directory:  {self.input_path}")
                print(f"Output Directory: {self.output_path}")
                print(f"Convert From:     {self.input_driver} ({self.input_driver_ext})")
                print(f"Convert To:       {self.conversion_driver} ({self.conversion_driver_ext})")
                if self.conversion_crs:
                    print(f"Output CRS:       {self.conversion_crs}")
                print("="*60 + "\n")
                
                # Run batch conversion — pass the input DIRECTORY path
                # batch_convert will scan for all matching files inside
                batch_convert(
                    self.input_path, 
                    self.output_path, 
                    self.input_driver, 
                    self.input_driver_ext, 
                    self.conversion_driver, 
                    self.conversion_driver_ext, 
                    conversion_crs=self.conversion_crs
                )
                
                # Save conversion preferences
                self.save_config()
                
                print("\n" + "="*60)
                print("✓ CONVERSION COMPLETED SUCCESSFULLY!")
                print(f"Output Directory: {self.output_path}")
                print("="*60 + "\n")
                
                self.status_label.config(text=f'✓ Conversion completed successfully! Saved to: {self.output_path}', foreground='green')
                messagebox.showinfo(
                    title='Success', 
                    message=f'Conversion completed!\n\nAll files have been saved to:\n{self.output_path}'
                )
                
            except Exception as error:
                print(f"\n✗ ERROR: {error}\n")
                self.status_label.config(text=f'✗ Error: {str(error)}', foreground='red')
                messagebox.showerror(
                    title='Conversion Error', 
                    message=f'Error during conversion:\n{str(error)}'
                )

    def search_files(self):
        """Search for files and display complete file details, metadata and full descriptions"""
        search_keyword = self.search_entry.get().strip().lower()
        
        if not search_keyword:
            messagebox.showwarning('Warning', 'Please enter a search keyword')
            return
        
        if not self.input_path and not self.output_path:
            messagebox.showwarning('Warning', 'Please select an input or output directory first')
            return
            
        try:
            import geopandas as gpd
            import pandas as pd
            import rasterio
        except ImportError:
            gpd = None
            pd = None
            rasterio = None
        
        # Get all files from input and output directories
        all_files = []
        if self.input_path and os.path.isdir(self.input_path):
            all_files.extend([os.path.join(self.input_path, f) for f in os.listdir(self.input_path)
                         if os.path.isfile(os.path.join(self.input_path, f))])
                         
        if self.output_path and os.path.isdir(self.output_path):
            all_files.extend([os.path.join(self.output_path, f) for f in os.listdir(self.output_path)
                         if os.path.isfile(os.path.join(self.output_path, f))])
                         
        # Remove duplicates if input and output path are the same
        all_files = list(set(all_files))
        
        if not all_files:
            messagebox.showwarning('Warning', 'No files found in selected directories')
            return
        
        # Clear previous results
        self.search_results_text.config(state='normal')
        self.search_results_text.delete('1.0', 'end')
        
        found_matches = False
        results_text = ""
        match_count = 0
        
        # Search through files
        for file_path in all_files:
            try:
                file_name = os.path.basename(file_path)
                file_size = os.path.getsize(file_path)
                file_ext = os.path.splitext(file_path)[1].lower()
                
                # Check if keyword matches file name
                name_match = search_keyword in file_name.lower()
                
                content_match = False
                metadata_text = ""
                file_metadata = {} # To build the full description
                
                # Use GeoPandas for Vector GIS files
                is_vector = False
                if file_ext in ['.shp', '.geojson', '.gpkg', '.fgb'] and gpd is not None:
                    try:
                        gdf = gpd.read_file(file_path)
                        is_vector = True
                        crs_info = str(gdf.crs) if gdf.crs else "No CRS found"
                        row_count = len(gdf)
                        columns = list(gdf.columns)
                        
                        file_metadata['type'] = 'Vector GIS'
                        file_metadata['crs'] = crs_info
                        file_metadata['row_count'] = row_count
                        file_metadata['columns'] = columns
                        
                        metadata_text += f"CRS: {crs_info}\n"
                        metadata_text += f"Total Features: {row_count}\n"
                        metadata_text += f"Columns: {', '.join(columns)}\n"
                        
                        # Data Sample (First 3 rows)
                        metadata_text += f"\nData Sample (First 3 rows):\n"
                        metadata_text += str(gdf.head(3))
                        
                        if search_keyword in str(columns).lower() or search_keyword in crs_info.lower() or search_keyword in gdf.head(10).to_string().lower():
                            content_match = True
                    except Exception as e:
                        metadata_text += f"Could not read Vector metadata: {str(e)}\n"
                        
                # CSV handling
                elif file_ext == '.csv' and not is_vector:
                    try:
                        import pandas as pd
                        df = pd.read_csv(file_path)
                        # ... (rest of pandas logic remains or we use GDAL CSV driver)
                        columns = list(df.columns)
                        row_count = len(df)
                        file_metadata['type'] = 'CSV Table'
                        file_metadata['row_count'] = row_count
                        file_metadata['columns'] = columns
                        metadata_text += f"Total Rows: {row_count}\n"
                        metadata_text += f"Columns: {', '.join(columns)}\n"
                        metadata_text += f"\nData Sample (First 3 rows):\n"
                        metadata_text += str(df.head(3))
                        if search_keyword in str(columns).lower() or search_keyword in df.head(10).to_string().lower():
                            content_match = True
                    except Exception as e:
                        metadata_text += f"Could not read CSV: {str(e)}\n"
                
                # Use Rasterio for Raster files
                elif file_ext in ['.tif', '.tiff', '.png', '.jpg', '.jpeg'] and rasterio is not None:
                    try:
                        with rasterio.open(file_path) as src:
                            crs_info = str(src.crs) if src.crs else "No CRS found"
                            file_metadata['type'] = 'Raster Image'
                            file_metadata['crs'] = crs_info
                            file_metadata['width'] = src.width
                            file_metadata['height'] = src.height
                            file_metadata['bands'] = src.count
                            
                            metadata_text += f"Format: Raster ({src.driver})\n"
                            metadata_text += f"CRS: {crs_info}\n"
                            metadata_text += f"Dimensions: {src.width} x {src.height} pixels\n"
                            metadata_text += f"Bands: {src.count}\n"
                            metadata_text += f"Data Type: {src.dtypes[0]}\n"
                            
                            if search_keyword in crs_info.lower() or search_keyword in src.driver.lower():
                                content_match = True
                    except Exception as e:
                        metadata_text += f"Could not read raster metadata: {str(e)}\n"

                # Fallback for other files
                else:
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            file_content = f.read()
                        
                        metadata_text += "File Content Preview (First 500 chars):\n"
                        metadata_text += file_content[:500] + ("..." if len(file_content) > 500 else "")
                        
                        if search_keyword in file_content.lower():
                            content_match = True
                    except Exception as e:
                        metadata_text += f"Could not read file content: {str(e)}\n"

                # --- GENERATE FULL DESCRIPTION ---
                full_description = ""
                # 1. Check known file descriptions
                if file_name in self.known_file_descriptions:
                    full_description = self.known_file_descriptions[file_name]
                # 2. Build from metadata if not known
                else:
                    desc_parts = []
                    if 'type' in file_metadata:
                        desc_parts.append(f"This is a {file_metadata['type']} file.")
                    else:
                        desc_parts.append(f"This is a {file_ext.upper()[1:] if file_ext else 'generic'} file.")
                        
                    if 'row_count' in file_metadata:
                        desc_parts.append(f"It contains {file_metadata['row_count']} data records.")
                    
                    if 'columns' in file_metadata:
                        cols = file_metadata['columns']
                        desc_parts.append(f"Key data fields include: {', '.join(cols[:5])}{' and more' if len(cols) > 5 else ''}.")
                        
                    if 'crs' in file_metadata and file_metadata['crs'] != "No CRS found":
                        desc_parts.append(f"The data is georeferenced using the {file_metadata['crs']} coordinate system.")
                        
                    if 'width' in file_metadata:
                        desc_parts.append(f"The image resolution is {file_metadata['width']}x{file_metadata['height']} pixels across {file_metadata['bands']} band(s).")
                    
                    # 3. Add format-specific generic description
                    if file_ext in self.format_descriptions:
                        desc_parts.append(f"\nFormat Info: {self.format_descriptions[file_ext]}")
                        
                    full_description = " ".join(desc_parts)

                # Check if keyword matches the description
                if search_keyword in full_description.lower():
                    content_match = True
                
                # --- DISPLAY RESULTS IF MATCHED ---
                if name_match or content_match:
                    found_matches = True
                    match_count += 1
                    
                    results_text += f"\n{'='*80}\n"
                    results_text += f"📄 FILE REPORT: {file_name}\n"
                    results_text += f"{'='*80}\n"
                    
                    results_text += f"FULL DESCRIPTION:\n"
                    results_text += f"{full_description}\n"
                    results_text += f"{'-'*40}\n"
                    
                    results_text += f"FILE PROPERTIES:\n"
                    results_text += f"  - Type: {file_ext if file_ext else 'Unknown'}\n"
                    results_text += f"  - Size: {file_size:,} bytes\n"
                    results_text += f"  - Location: {file_path}\n"
                    results_text += f"{'-'*40}\n"
                    
                    results_text += f"DETAILED METADATA & DATA PREVIEW:\n"
                    results_text += metadata_text
                    results_text += f"\n{'-'*80}\n\n"
            
            except Exception as error:
                results_text += f"\nError processing {os.path.basename(file_path)}: {str(error)}\n"
        
        if found_matches:
            self.search_results_text.insert('1.0', results_text)
            self.status_label.config(text=f'✓ Found {match_count} matching file(s) with full descriptions', foreground='green')
        else:
            no_match_text = f"No files found matching keyword: '{search_keyword}'\n\n"
            no_match_text += "Searched in file names, content, metadata, and descriptions.\n"
            self.search_results_text.insert('1.0', no_match_text)
            self.status_label.config(text=f'✗ No matches found for "{search_keyword}"', foreground='red')
        
        self.search_results_text.config(state='disabled')

    def run(self):
        """Start the GUI"""
        self.main_window.mainloop()

# Run the GUI
if __name__ == '__main__':
    convertFrontEnd = ConvertGui()
    convertFrontEnd.run()
