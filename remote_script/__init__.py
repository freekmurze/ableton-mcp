# AbletonAI remote script
from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback
import queue
import os

# Constants for socket communication (can be overridden via environment)
DEFAULT_PORT = int(os.environ.get("ABLETON_MCP_PORT", "9877"))
HOST = os.environ.get("ABLETON_MCP_HOST", "localhost")
CLIENT_TIMEOUT = float(os.environ.get("ABLETON_MCP_CLIENT_TIMEOUT", "300.0"))  # 5 min timeout
MAX_CLIENTS = int(os.environ.get("ABLETON_MCP_MAX_CLIENTS", "10"))
MAX_BUFFER_SIZE = int(os.environ.get("ABLETON_MCP_MAX_BUFFER", "1048576"))  # 1MB

def create_instance(c_instance):
    """Create and return the AbletonAI script instance"""
    return AbletonAI(c_instance)

class AbletonAI(ControlSurface):
    """AbletonAI Remote Script for Ableton Live"""

    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonAI Remote Script initializing...")

        # Socket server for communication
        self.server = None
        self.client_threads = []
        self._threads_lock = threading.Lock()  # Thread safety for client_threads
        self.server_thread = None
        self.running = False

        # Cache the song reference for easier access
        self._song = self.song()

        # Start the socket server
        self.start_server()

        self.log_message("AbletonAI initialized")

        # Show a message in Ableton
        self.show_message("AbletonAI: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonAI disconnecting...")
        self.running = False

        # Stop the server
        if self.server:
            try:
                self.server.close()
            except (socket.error, OSError) as e:
                self.log_message("Error closing server socket: " + str(e))

        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)

        # Clean up any client threads (thread-safe)
        with self._threads_lock:
            for client_thread in self.client_threads[:]:
                if client_thread.is_alive():
                    self.log_message("Client thread still alive during disconnect")
            self.client_threads = []

        ControlSurface.disconnect(self)
        self.log_message("AbletonAI disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonAI: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)

            while self.running:
                try:
                    # Check client count before accepting (thread-safe)
                    with self._threads_lock:
                        active_count = len([t for t in self.client_threads if t.is_alive()])
                        if active_count >= MAX_CLIENTS:
                            self.log_message("Max clients reached ({0}), waiting...".format(MAX_CLIENTS))
                            time.sleep(1.0)
                            continue

                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonAI: Client connected")

                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()

                    # Keep track of client threads (thread-safe)
                    with self._threads_lock:
                        self.client_threads.append(client_thread)
                        # Clean up finished client threads
                        self.client_threads = [t for t in self.client_threads if t.is_alive()]

                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except (socket.error, OSError) as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
                except Exception as e:
                    if self.running:
                        self.log_message("Unexpected server error: " + str(e))
                    time.sleep(0.5)

            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread fatal error: " + str(e))
            self.log_message(traceback.format_exc())
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(CLIENT_TIMEOUT)  # Add timeout to prevent DoS
        buffer = ''  # Changed from b'' to '' for Python 2

        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)

                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break

                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        decoded = data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        decoded = data
                    except UnicodeDecodeError as e:
                        self.log_message("Invalid UTF-8 data received: " + str(e))
                        continue

                    buffer += decoded

                    # Check buffer size limit to prevent memory DoS
                    if len(buffer) > MAX_BUFFER_SIZE:
                        self.log_message("Buffer overflow - client sent too much data")
                        break
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except (socket.error, OSError) as send_err:
                        # If we can't send the error, the connection is probably dead
                        self.log_message("Failed to send error response: " + str(send_err))
                        break

                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except socket.timeout:
            self.log_message("Client timed out after {0} seconds".format(CLIENT_TIMEOUT))
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
            self.log_message(traceback.format_exc())
        finally:
            try:
                client.close()
            except (socket.error, OSError) as e:
                self.log_message("Error closing client socket: " + str(e))
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response.

        Dispatch is a table lookup (see _DISPATCH). Read commands run on the
        socket thread; commands that mutate Live are scheduled on Live's main
        thread, because touching Live off the main thread crashes it.
        """
        command_type = command.get("type", "")
        params = command.get("params", {})
        response = {"status": "success", "result": {}}
        try:
            entry = self._DISPATCH.get(command_type)
            if entry is None:
                response["status"] = "error"
                response["message"] = "Unknown command: %s. Available commands include: get_session_info, get_track_info, set_track_volume, set_track_pan, create_clip, add_notes_to_clip, fire_scene, load_browser_item, etc." % command_type
                return response
            method_name, is_write = entry
            handler = getattr(self, method_name)
            if not is_write:
                response["result"] = handler(params)
            else:
                # Use a thread-safe approach with a response queue
                # maxsize=10 prevents unbounded memory growth
                response_queue = queue.Queue(maxsize=10)

                def main_thread_task():
                    try:
                        result = handler(params)
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})

                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    main_thread_task()

                try:
                    task_response = response_queue.get(timeout=10.0)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)

        return response

    _DISPATCH = {
        "browse_path": ("_rd_browse_path", False),
        "get_all_scenes": ("_rd_get_all_scenes", False),
        "get_all_track_names": ("_rd_get_all_track_names", False),
        "get_arrangement_length": ("_rd_get_arrangement_length", False),
        "get_arrangement_overdub": ("_rd_get_arrangement_overdub", False),
        "get_audio_clip_file_path": ("_rd_get_audio_clip_file_path", False),
        "get_available_inputs": ("_rd_get_available_inputs", False),
        "get_available_outputs": ("_rd_get_available_outputs", False),
        "get_back_to_arrangement": ("_rd_get_back_to_arrangement", False),
        "get_browser_children": ("_rd_get_browser_children", False),
        "get_browser_item": ("_rd_get_browser_item", False),
        "get_browser_items_at_path": ("_rd_get_browser_items_at_path", False),
        "get_browser_tree": ("_rd_get_browser_tree", False),
        "get_can_capture_midi": ("_rd_get_can_capture_midi", False),
        "get_clip_color": ("_rd_get_clip_color", False),
        "get_clip_end_time": ("_rd_get_clip_end_time", False),
        "get_clip_fades": ("_rd_get_clip_fades", False),
        "get_clip_follow_action": ("_rd_get_clip_follow_action", False),
        "get_clip_gain": ("_rd_get_clip_gain", False),
        "get_clip_has_envelopes": ("_rd_get_clip_has_envelopes", False),
        "get_clip_info": ("_rd_get_clip_info", False),
        "get_clip_is_playing": ("_rd_get_clip_is_playing", False),
        "get_clip_launch_mode": ("_rd_get_clip_launch_mode", False),
        "get_clip_launch_quantization": ("_rd_get_clip_launch_quantization", False),
        "get_clip_loop": ("_rd_get_clip_loop", False),
        "get_clip_notes": ("_rd_get_clip_notes", False),
        "get_clip_pitch": ("_rd_get_clip_pitch", False),
        "get_clip_playing_position": ("_rd_get_clip_playing_position", False),
        "get_clip_ram_mode": ("_rd_get_clip_ram_mode", False),
        "get_clip_start_end_markers": ("_rd_get_clip_start_end_markers", False),
        "get_clip_start_time": ("_rd_get_clip_start_time", False),
        "get_clip_trigger_quantization": ("_rd_get_clip_trigger_quantization", False),
        "get_clip_velocity_amount": ("_rd_get_clip_velocity_amount", False),
        "get_count_in_duration": ("_rd_get_count_in_duration", False),
        "get_cpu_load": ("_rd_get_cpu_load", False),
        "get_crossfader": ("_rd_get_crossfader", False),
        "get_cue_volume": ("_rd_get_cue_volume", False),
        "get_current_song_time": ("_rd_get_current_song_time", False),
        "get_current_view": ("_rd_get_current_view", False),
        "get_detail_clip": ("_rd_get_detail_clip", False),
        "get_device_parameters": ("_rd_get_device_parameters", False),
        "get_device_view_state": ("_rd_get_device_view_state", False),
        "get_draw_mode": ("_rd_get_draw_mode", False),
        "get_drum_pad_info": ("_rd_get_drum_pad_info", False),
        "get_drum_rack_pads": ("_rd_get_drum_rack_pads", False),
        "get_exclusive_arm": ("_rd_get_exclusive_arm", False),
        "get_exclusive_solo": ("_rd_get_exclusive_solo", False),
        "get_follow_mode": ("_rd_get_follow_mode", False),
        "get_grid_quantization": ("_rd_get_grid_quantization", False),
        "get_groove_amount": ("_rd_get_groove_amount", False),
        "get_highlighted_clip_slot": ("_rd_get_highlighted_clip_slot", False),
        "get_locators": ("_rd_get_locators", False),
        "get_master_info": ("_rd_get_master_info", False),
        "get_master_output_meter": ("_rd_get_master_output_meter", False),
        "get_metronome_state": ("_rd_get_metronome_state", False),
        "get_midi_recording_quantization": ("_rd_get_midi_recording_quantization", False),
        "get_notes_in_range": ("_rd_get_notes_in_range", False),
        "get_playback_position": ("_rd_get_playback_position", False),
        "get_punch_settings": ("_rd_get_punch_settings", False),
        "get_rack_macros": ("_rd_get_rack_macros", False),
        "get_record_mode": ("_rd_get_record_mode", False),
        "get_return_track_info": ("_rd_get_return_track_info", False),
        "get_return_tracks": ("_rd_get_return_tracks", False),
        "get_scale_notes": ("_rd_get_scale_notes", False),
        "get_scene_color": ("_rd_get_scene_color", False),
        "get_selected_device": ("_rd_get_selected_device", False),
        "get_selected_scene": ("_rd_get_selected_scene", False),
        "get_selected_track": ("_rd_get_selected_track", False),
        "get_send_level": ("_rd_get_send_level", False),
        "get_send_pre_post": ("_rd_get_send_pre_post", False),
        "get_session_automation_record": ("_rd_get_session_automation_record", False),
        "get_session_info": ("_rd_get_session_info", False),
        "get_session_path": ("_rd_get_session_path", False),
        "get_signature": ("_rd_get_signature", False),
        "get_simpler_parameters": ("_rd_get_simpler_parameters", False),
        "get_simpler_sample_info": ("_rd_get_simpler_sample_info", False),
        "get_song_length": ("_rd_get_song_length", False),
        "get_song_root_note": ("_rd_get_song_root_note", False),
        "get_song_scale": ("_rd_get_song_scale", False),
        "get_song_scale_names": ("_rd_get_song_scale_names", False),
        "get_swing_amount": ("_rd_get_swing_amount", False),
        "get_track_available_input_types": ("_rd_get_track_available_input_types", False),
        "get_track_available_output_types": ("_rd_get_track_available_output_types", False),
        "get_track_capabilities": ("_rd_get_track_capabilities", False),
        "get_track_color": ("_rd_get_track_color", False),
        "get_track_crossfade_assign": ("_rd_get_track_crossfade_assign", False),
        "get_track_delay": ("_rd_get_track_delay", False),
        "get_track_fired_slot_index": ("_rd_get_track_fired_slot_index", False),
        "get_track_implicit_arm": ("_rd_get_track_implicit_arm", False),
        "get_track_info": ("_rd_get_track_info", False),
        "get_track_input_routing": ("_rd_get_track_input_routing", False),
        "get_track_is_foldable": ("_rd_get_track_is_foldable", False),
        "get_track_is_grouped": ("_rd_get_track_is_grouped", False),
        "get_track_output_meter": ("_rd_get_track_output_meter", False),
        "get_track_output_routing": ("_rd_get_track_output_routing", False),
        "get_track_playing_slot_index": ("_rd_get_track_playing_slot_index", False),
        "get_view_zoom": ("_rd_get_view_zoom", False),
        "get_warp_markers": ("_rd_get_warp_markers", False),
        "health_check": ("_rd_health_check", False),
        "is_session_modified": ("_rd_is_session_modified", False),
        "search_browser": ("_rd_search_browser", False),
        "set_master_pan": ("_rd_set_master_pan", False),
        "set_master_volume": ("_rd_set_master_volume", False),
        "add_notes_to_clip": ("_wr_add_notes_to_clip", True),
        "add_notes_with_probability": ("_wr_add_notes_with_probability", True),
        "add_warp_marker": ("_wr_add_warp_marker", True),
        "apply_groove": ("_wr_apply_groove", True),
        "capture_midi": ("_wr_capture_midi", True),
        "clear_clip_automation": ("_wr_clear_clip_automation", True),
        "commit_groove": ("_wr_commit_groove", True),
        "continue_playing": ("_wr_continue_playing", True),
        "create_audio_track": ("_wr_create_audio_track", True),
        "create_clip": ("_wr_create_clip", True),
        "create_group_track": ("_wr_create_group_track", True),
        "create_locator": ("_wr_create_locator", True),
        "create_midi_track": ("_wr_create_midi_track", True),
        "create_arrangement_midi_clip": ("_wr_create_arrangement_midi_clip", True),
        "get_master_device_parameters": ("_rd_get_master_device_parameters", False),
        "set_master_device_parameter": ("_wr_set_master_device_parameter", True),
        "get_return_device_parameters": ("_rd_get_return_device_parameters", False),
        "set_return_device_parameter": ("_wr_set_return_device_parameter", True),
        "create_return_track": ("_wr_create_return_track", True),
        "create_scene": ("_wr_create_scene", True),
        "delete_clip": ("_wr_delete_clip", True),
        "delete_device": ("_wr_delete_device", True),
        "delete_locator": ("_wr_delete_locator", True),
        "delete_return_track": ("_wr_delete_return_track", True),
        "delete_scene": ("_wr_delete_scene", True),
        "delete_track": ("_wr_delete_track", True),
        "delete_warp_marker": ("_wr_delete_warp_marker", True),
        "deselect_all_notes": ("_wr_deselect_all_notes", True),
        "duplicate_clip": ("_wr_duplicate_clip", True),
        "duplicate_clip_loop": ("_wr_duplicate_clip_loop", True),
        "duplicate_scene": ("_wr_duplicate_scene", True),
        "duplicate_track": ("_wr_duplicate_track", True),
        "fire_clip": ("_wr_fire_clip", True),
        "fire_scene": ("_wr_fire_scene", True),
        "flatten_track": ("_wr_flatten_track", True),
        "focus_view": ("_wr_focus_view", True),
        "fold_track": ("_wr_fold_track", True),
        "freeze_track": ("_wr_freeze_track", True),
        "generate_bassline": ("_wr_generate_bassline", True),
        "generate_drum_pattern": ("_wr_generate_drum_pattern", True),
        "get_chain_device_parameters": ("_wr_get_chain_device_parameters", True),
        "get_clip_automation": ("_wr_get_clip_automation", True),
        "get_clip_warp_info": ("_wr_get_clip_warp_info", True),
        "get_device_by_name": ("_wr_get_device_by_name", True),
        "get_groove_pool": ("_wr_get_groove_pool", True),
        "get_rack_chains": ("_wr_get_rack_chains", True),
        "get_track_monitoring": ("_wr_get_track_monitoring", True),
        "humanize_clip_timing": ("_wr_humanize_clip_timing", True),
        "humanize_clip_velocity": ("_wr_humanize_clip_velocity", True),
        "jump_to_cue_point": ("_wr_jump_to_cue_point", True),
        "jump_to_next_cue": ("_wr_jump_to_next_cue", True),
        "jump_to_prev_cue": ("_wr_jump_to_prev_cue", True),
        "jump_to_time": ("_wr_jump_to_time", True),
        "load_browser_item": ("_wr_load_browser_item", True),
        "load_browser_item_to_return": ("_wr_load_browser_item_to_return", True),
        "load_device_preset": ("_wr_load_device_preset", True),
        "move_clip_notes": ("_wr_move_clip_notes", True),
        "move_device": ("_wr_move_device", True),
        "move_device_left": ("_wr_move_device_left", True),
        "move_device_right": ("_wr_move_device_right", True),
        "quantize_clip": ("_wr_quantize_clip", True),
        "quantize_clip_notes": ("_wr_quantize_clip_notes", True),
        "re_enable_automation": ("_wr_re_enable_automation", True),
        "redo": ("_wr_redo", True),
        "remove_all_notes": ("_wr_remove_all_notes", True),
        "remove_notes": ("_wr_remove_notes", True),
        "scrub_by": ("_wr_scrub_by", True),
        "select_clip": ("_wr_select_clip", True),
        "select_device": ("_wr_select_device", True),
        "select_rack_chain": ("_wr_select_rack_chain", True),
        "select_scene": ("_wr_select_scene", True),
        "select_track": ("_wr_select_track", True),
        "set_arrangement_loop": ("_wr_set_arrangement_loop", True),
        "set_arrangement_overdub": ("_wr_set_arrangement_overdub", True),
        "set_chain_device_parameter": ("_wr_set_chain_device_parameter", True),
        "set_clip_automation": ("_wr_set_clip_automation", True),
        "set_clip_color": ("_wr_set_clip_color", True),
        "set_clip_end_marker": ("_wr_set_clip_end_marker", True),
        "set_clip_end_time": ("_wr_set_clip_end_time", True),
        "set_clip_fade_in": ("_wr_set_clip_fade_in", True),
        "set_clip_fade_out": ("_wr_set_clip_fade_out", True),
        "set_clip_follow_action": ("_wr_set_clip_follow_action", True),
        "set_clip_gain": ("_wr_set_clip_gain", True),
        "set_clip_launch_mode": ("_wr_set_clip_launch_mode", True),
        "set_clip_launch_quantization": ("_wr_set_clip_launch_quantization", True),
        "set_clip_loop": ("_wr_set_clip_loop", True),
        "set_clip_name": ("_wr_set_clip_name", True),
        "set_clip_notes": ("_wr_set_clip_notes", True),
        "set_clip_pitch": ("_wr_set_clip_pitch", True),
        "set_clip_ram_mode": ("_wr_set_clip_ram_mode", True),
        "set_clip_start_marker": ("_wr_set_clip_start_marker", True),
        "set_clip_start_time": ("_wr_set_clip_start_time", True),
        "set_clip_trigger_quantization": ("_wr_set_clip_trigger_quantization", True),
        "set_clip_velocity_amount": ("_wr_set_clip_velocity_amount", True),
        "set_clip_warp_mode": ("_wr_set_clip_warp_mode", True),
        "set_count_in_duration": ("_wr_set_count_in_duration", True),
        "set_crossfader": ("_wr_set_crossfader", True),
        "set_cue_volume": ("_wr_set_cue_volume", True),
        "set_current_song_time": ("_wr_set_current_song_time", True),
        "set_detail_clip": ("_wr_set_detail_clip", True),
        "set_device_collapsed": ("_wr_set_device_collapsed", True),
        "set_device_parameter": ("_wr_set_device_parameter", True),
        "set_draw_mode": ("_wr_set_draw_mode", True),
        "set_drum_pad_name": ("_wr_set_drum_pad_name", True),
        "set_drum_rack_pad_mute": ("_wr_set_drum_rack_pad_mute", True),
        "set_drum_rack_pad_solo": ("_wr_set_drum_rack_pad_solo", True),
        "set_exclusive_arm": ("_wr_set_exclusive_arm", True),
        "set_exclusive_solo": ("_wr_set_exclusive_solo", True),
        "set_follow_mode": ("_wr_set_follow_mode", True),
        "set_grid_quantization": ("_wr_set_grid_quantization", True),
        "set_groove_amount": ("_wr_set_groove_amount", True),
        "set_metronome": ("_wr_set_metronome", True),
        "set_midi_recording_quantization": ("_wr_set_midi_recording_quantization", True),
        "set_overdub": ("_wr_set_overdub", True),
        "set_punch_in": ("_wr_set_punch_in", True),
        "set_punch_out": ("_wr_set_punch_out", True),
        "set_rack_macro": ("_wr_set_rack_macro", True),
        "set_return_pan": ("_wr_set_return_pan", True),
        "set_return_volume": ("_wr_set_return_volume", True),
        "set_scene_color": ("_wr_set_scene_color", True),
        "set_scene_name": ("_wr_set_scene_name", True),
        "set_send_level": ("_wr_set_send_level", True),
        "set_session_automation_record": ("_wr_set_session_automation_record", True),
        "set_signature": ("_wr_set_signature", True),
        "set_song_root_note": ("_wr_set_song_root_note", True),
        "set_song_scale": ("_wr_set_song_scale", True),
        "set_swing_amount": ("_wr_set_swing_amount", True),
        "set_tempo": ("_wr_set_tempo", True),
        "set_track_arm": ("_wr_set_track_arm", True),
        "set_track_color": ("_wr_set_track_color", True),
        "set_track_crossfade_assign": ("_wr_set_track_crossfade_assign", True),
        "set_track_delay": ("_wr_set_track_delay", True),
        "set_track_implicit_arm": ("_wr_set_track_implicit_arm", True),
        "set_track_input_routing": ("_wr_set_track_input_routing", True),
        "set_track_monitoring": ("_wr_set_track_monitoring", True),
        "set_track_mute": ("_wr_set_track_mute", True),
        "set_track_name": ("_wr_set_track_name", True),
        "set_track_output_routing": ("_wr_set_track_output_routing", True),
        "set_track_pan": ("_wr_set_track_pan", True),
        "set_track_solo": ("_wr_set_track_solo", True),
        "set_track_volume": ("_wr_set_track_volume", True),
        "solo_exclusive": ("_wr_solo_exclusive", True),
        "start_playback": ("_wr_start_playback", True),
        "start_recording": ("_wr_start_recording", True),
        "stop_all_clips": ("_wr_stop_all_clips", True),
        "stop_clip": ("_wr_stop_clip", True),
        "stop_playback": ("_wr_stop_playback", True),
        "stop_recording": ("_wr_stop_recording", True),
        "stop_scene": ("_wr_stop_scene", True),
        "tap_tempo": ("_wr_tap_tempo", True),
        "toggle_arrangement_record": ("_wr_toggle_arrangement_record", True),
        "toggle_device": ("_wr_toggle_device", True),
        "toggle_session_record": ("_wr_toggle_session_record", True),
        "transpose_notes": ("_wr_transpose_notes", True),
        "trigger_back_to_arrangement": ("_wr_trigger_back_to_arrangement", True),
        "unarm_all": ("_wr_unarm_all", True),
        "undo": ("_wr_undo", True),
        "unfold_track": ("_wr_unfold_track", True),
        "ungroup_tracks": ("_wr_ungroup_tracks", True),
        "unmute_all": ("_wr_unmute_all", True),
        "unsolo_all": ("_wr_unsolo_all", True),
    }

    def _rd_browse_path(self, params):
        response = {}
        path = params.get("path", [])
        response["result"] = self._browse_path(path)
        return response.get("result")

    def _rd_get_all_scenes(self, params):
        response = {}
        response["result"] = self._get_all_scenes()
        return response.get("result")

    def _rd_get_all_track_names(self, params):
        response = {}
        response["result"] = self._get_all_track_names()
        return response.get("result")

    def _rd_get_arrangement_length(self, params):
        response = {}
        response["result"] = self._get_arrangement_length()
        return response.get("result")

    def _rd_get_arrangement_overdub(self, params):
        response = {}
        response["result"] = self._get_arrangement_overdub()
        return response.get("result")

    def _rd_get_audio_clip_file_path(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_audio_clip_file_path(track_index, clip_index)
        return response.get("result")

    def _rd_get_available_inputs(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_available_inputs(track_index)
        return response.get("result")

    def _rd_get_available_outputs(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_available_outputs(track_index)
        return response.get("result")

    def _rd_get_back_to_arrangement(self, params):
        response = {}
        response["result"] = self._get_back_to_arrangement()
        return response.get("result")

    def _rd_get_browser_children(self, params):
        response = {}
        uri = params.get("uri", "")
        response["result"] = self._get_browser_children(uri)
        return response.get("result")

    def _rd_get_browser_item(self, params):
        response = {}
        uri = params.get("uri", None)
        path = params.get("path", None)
        response["result"] = self._get_browser_item(uri, path)
        return response.get("result")

    def _rd_get_browser_items_at_path(self, params):
        response = {}
        path = params.get("path", "")
        response["result"] = self.get_browser_items_at_path(path)
        return response.get("result")

    def _rd_get_browser_tree(self, params):
        response = {}
        category_type = params.get("category_type", "all")
        response["result"] = self.get_browser_tree(category_type)
        return response.get("result")

    def _rd_get_can_capture_midi(self, params):
        response = {}
        response["result"] = self._get_can_capture_midi()
        return response.get("result")

    def _rd_get_clip_color(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_color(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_end_time(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_end_time(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_fades(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_fades(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_follow_action(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_follow_action(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_gain(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_gain(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_has_envelopes(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_has_envelopes(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_info(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_info(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_is_playing(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_is_playing(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_launch_mode(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_launch_mode(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_launch_quantization(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_launch_quantization(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_loop(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_loop(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_notes(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_notes(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_pitch(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_pitch(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_playing_position(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_playing_position(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_ram_mode(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_ram_mode(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_start_end_markers(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_start_end_markers(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_start_time(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_start_time(track_index, clip_index)
        return response.get("result")

    def _rd_get_clip_trigger_quantization(self, params):
        response = {}
        response["result"] = self._get_clip_trigger_quantization()
        return response.get("result")

    def _rd_get_clip_velocity_amount(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_clip_velocity_amount(track_index, clip_index)
        return response.get("result")

    def _rd_get_count_in_duration(self, params):
        response = {}
        response["result"] = self._get_count_in_duration()
        return response.get("result")

    def _rd_get_cpu_load(self, params):
        response = {}
        response["result"] = self._get_cpu_load()
        return response.get("result")

    def _rd_get_crossfader(self, params):
        response = {}
        response["result"] = self._get_crossfader()
        return response.get("result")

    def _rd_get_cue_volume(self, params):
        response = {}
        response["result"] = self._get_cue_volume()
        return response.get("result")

    def _rd_get_current_song_time(self, params):
        response = {}
        response["result"] = self._get_current_song_time()
        return response.get("result")

    def _rd_get_current_view(self, params):
        response = {}
        response["result"] = self._get_current_view()
        return response.get("result")

    def _rd_get_detail_clip(self, params):
        response = {}
        response["result"] = self._get_detail_clip()
        return response.get("result")

    def _rd_get_device_parameters(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_device_parameters(track_index, device_index)
        return response.get("result")

    def _rd_get_device_view_state(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_device_view_state(track_index, device_index)
        return response.get("result")

    def _rd_get_draw_mode(self, params):
        response = {}
        response["result"] = self._get_draw_mode()
        return response.get("result")

    def _rd_get_drum_pad_info(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        pad_index = params.get("pad_index", 0)
        response["result"] = self._get_drum_pad_info(track_index, device_index, pad_index)
        return response.get("result")

    def _rd_get_drum_rack_pads(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_drum_rack_pads(track_index, device_index)
        return response.get("result")

    def _rd_get_exclusive_arm(self, params):
        response = {}
        response["result"] = self._get_exclusive_arm()
        return response.get("result")

    def _rd_get_exclusive_solo(self, params):
        response = {}
        response["result"] = self._get_exclusive_solo()
        return response.get("result")

    def _rd_get_follow_mode(self, params):
        response = {}
        response["result"] = self._get_follow_mode()
        return response.get("result")

    def _rd_get_grid_quantization(self, params):
        response = {}
        response["result"] = self._get_grid_quantization()
        return response.get("result")

    def _rd_get_groove_amount(self, params):
        response = {}
        response["result"] = self._get_groove_amount()
        return response.get("result")

    def _rd_get_highlighted_clip_slot(self, params):
        response = {}
        response["result"] = self._get_highlighted_clip_slot()
        return response.get("result")

    def _rd_get_locators(self, params):
        response = {}
        response["result"] = self._get_locators()
        return response.get("result")

    def _rd_get_master_info(self, params):
        response = {}
        response["result"] = self._get_master_info()
        return response.get("result")

    def _rd_get_master_output_meter(self, params):
        response = {}
        response["result"] = self._get_master_output_meter()
        return response.get("result")

    def _rd_get_metronome_state(self, params):
        response = {}
        response["result"] = self._get_metronome_state()
        return response.get("result")

    def _rd_get_midi_recording_quantization(self, params):
        response = {}
        response["result"] = self._get_midi_recording_quantization()
        return response.get("result")

    def _rd_get_notes_in_range(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        start_time = params.get("start_time", 0)
        end_time = params.get("end_time", 4)
        pitch_start = params.get("pitch_start", 0)
        pitch_end = params.get("pitch_end", 127)
        response["result"] = self._get_notes_in_range(track_index, clip_index, start_time, end_time, pitch_start, pitch_end)
        return response.get("result")

    def _rd_get_playback_position(self, params):
        response = {}
        response["result"] = self._get_playback_position()
        return response.get("result")

    def _rd_get_punch_settings(self, params):
        response = {}
        response["result"] = self._get_punch_settings()
        return response.get("result")

    def _rd_get_rack_macros(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_rack_macros(track_index, device_index)
        return response.get("result")

    def _rd_get_record_mode(self, params):
        response = {}
        response["result"] = self._get_record_mode()
        return response.get("result")

    def _rd_get_return_track_info(self, params):
        response = {}
        return_index = params.get("return_index", 0)
        response["result"] = self._get_return_track_info(return_index)
        return response.get("result")

    def _rd_get_return_tracks(self, params):
        response = {}
        response["result"] = self._get_return_tracks()
        return response.get("result")

    def _rd_get_scale_notes(self, params):
        response = {}
        song_root = getattr(self._song, "root_note", 0)
        song_scale = getattr(self._song, "scale_name", "major")
        root = params.get("root", song_root)
        scale_type = params.get("scale_type", str(song_scale).lower().replace(" ", "_"))
        response["result"] = self._get_scale_notes(root, scale_type)
        return response.get("result")

    def _rd_get_scene_color(self, params):
        response = {}
        scene_index = params.get("scene_index", 0)
        response["result"] = self._get_scene_color(scene_index)
        return response.get("result")

    def _rd_get_selected_device(self, params):
        response = {}
        response["result"] = self._get_selected_device()
        return response.get("result")

    def _rd_get_selected_scene(self, params):
        response = {}
        response["result"] = self._get_selected_scene()
        return response.get("result")

    def _rd_get_selected_track(self, params):
        response = {}
        response["result"] = self._get_selected_track()
        return response.get("result")

    def _rd_get_send_level(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        send_index = params.get("send_index", 0)
        response["result"] = self._get_send_level(track_index, send_index)
        return response.get("result")

    def _rd_get_send_pre_post(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        send_index = params.get("send_index", 0)
        response["result"] = self._get_send_pre_post(track_index, send_index)
        return response.get("result")

    def _rd_get_session_automation_record(self, params):
        response = {}
        response["result"] = self._get_session_automation_record()
        return response.get("result")

    def _rd_get_session_info(self, params):
        response = {}
        response["result"] = self._get_session_info()
        return response.get("result")

    def _rd_get_session_path(self, params):
        response = {}
        response["result"] = self._get_session_path()
        return response.get("result")

    def _rd_get_signature(self, params):
        response = {}
        response["result"] = self._get_signature()
        return response.get("result")

    def _rd_get_simpler_parameters(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_simpler_parameters(track_index, device_index)
        return response.get("result")

    def _rd_get_simpler_sample_info(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        response["result"] = self._get_simpler_sample_info(track_index, device_index)
        return response.get("result")

    def _rd_get_song_length(self, params):
        response = {}
        response["result"] = self._get_song_length()
        return response.get("result")

    def _rd_get_song_root_note(self, params):
        response = {}
        response["result"] = self._get_song_root_note()
        return response.get("result")

    def _rd_get_song_scale(self, params):
        response = {}
        response["result"] = self._get_song_scale()
        return response.get("result")

    def _rd_get_song_scale_names(self, params):
        response = {}
        response["result"] = self._get_song_scale_names()
        return response.get("result")

    def _rd_get_swing_amount(self, params):
        response = {}
        response["result"] = self._get_swing_amount()
        return response.get("result")

    def _rd_get_track_available_input_types(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_available_input_types(track_index)
        return response.get("result")

    def _rd_get_track_available_output_types(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_available_output_types(track_index)
        return response.get("result")

    def _rd_get_track_capabilities(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_capabilities(track_index)
        return response.get("result")

    def _rd_get_track_color(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_color(track_index)
        return response.get("result")

    def _rd_get_track_crossfade_assign(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_crossfade_assign(track_index)
        return response.get("result")

    def _rd_get_track_delay(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_delay(track_index)
        return response.get("result")

    def _rd_get_track_fired_slot_index(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_fired_slot_index(track_index)
        return response.get("result")

    def _rd_get_track_implicit_arm(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_implicit_arm(track_index)
        return response.get("result")

    def _rd_get_track_info(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_info(track_index)
        return response.get("result")

    def _rd_get_track_input_routing(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_input_routing(track_index)
        return response.get("result")

    def _rd_get_track_is_foldable(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_is_foldable(track_index)
        return response.get("result")

    def _rd_get_track_is_grouped(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_is_grouped(track_index)
        return response.get("result")

    def _rd_get_track_output_meter(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_output_meter(track_index)
        return response.get("result")

    def _rd_get_track_output_routing(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_output_routing(track_index)
        return response.get("result")

    def _rd_get_track_playing_slot_index(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        response["result"] = self._get_track_playing_slot_index(track_index)
        return response.get("result")

    def _rd_get_view_zoom(self, params):
        response = {}
        response["result"] = self._get_view_zoom()
        return response.get("result")

    def _rd_get_warp_markers(self, params):
        response = {}
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        response["result"] = self._get_warp_markers(track_index, clip_index)
        return response.get("result")

    def _rd_health_check(self, params):
        response = {}
        response["result"] = self._health_check()
        return response.get("result")

    def _rd_is_session_modified(self, params):
        response = {}
        response["result"] = self._is_session_modified()
        return response.get("result")

    def _rd_search_browser(self, params):
        response = {}
        query = params.get("query", "")
        category = params.get("category", "all")
        response["result"] = self._search_browser(query, category)
        return response.get("result")

    def _rd_set_master_pan(self, params):
        response = {}
        pan = params.get("pan", 0.0)
        response["result"] = self._set_master_pan(pan)
        return response.get("result")

    def _rd_set_master_volume(self, params):
        response = {}
        volume = params.get("volume", 0.85)
        response["result"] = self._set_master_volume(volume)
        return response.get("result")

    def _wr_add_notes_to_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        notes = params.get("notes", [])
        result = self._add_notes_to_clip(track_index, clip_index, notes)
        return result

    def _wr_add_notes_with_probability(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        notes = params.get("notes", [])
        replace = params.get("replace", True)
        result = self._add_notes_with_probability(track_index, clip_index, notes, replace)
        return result

    def _wr_add_warp_marker(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        beat_time = params.get("beat_time", 0.0)
        sample_time = params.get("sample_time", None)
        result = self._add_warp_marker(track_index, clip_index, beat_time, sample_time)
        return result

    def _wr_apply_groove(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        groove_index = params.get("groove_index", 0)
        result = self._apply_groove(track_index, clip_index, groove_index)
        return result

    def _wr_capture_midi(self, params):
        result = None
        result = self._capture_midi()
        return result

    def _wr_clear_clip_automation(self, params):
        result = None
        result = self._clear_clip_automation(
            params.get("track_index", 0), params.get("clip_index", 0),
            params.get("parameter_name", ""), params.get("device_index", None))
        return result

    def _wr_commit_groove(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._commit_groove(track_index, clip_index)
        return result

    def _wr_continue_playing(self, params):
        result = None
        result = self._continue_playing()
        return result

    def _wr_create_audio_track(self, params):
        result = None
        index = params.get("index", -1)
        result = self._create_audio_track(index)
        return result

    def _wr_create_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        length = params.get("length", 4.0)
        result = self._create_clip(track_index, clip_index, length)
        return result

    def _wr_create_group_track(self, params):
        result = None
        track_indices = params.get("track_indices", [])
        name = params.get("name", "Group")
        result = self._create_group_track(track_indices, name)
        return result

    def _wr_create_locator(self, params):
        result = None
        time = params.get("time", 0.0)
        name = params.get("name", "")
        result = self._create_locator(time, name)
        return result

    def _wr_set_master_device_parameter(self, params):
        result = None
        result = self._set_master_device_parameter(
            params.get("device_index", 0), params.get("parameter_index", None),
            params.get("parameter_name", None), params.get("value", 0.0))
        return result

    def _wr_set_return_device_parameter(self, params):
        result = None
        result = self._set_return_device_parameter(
            params.get("return_index", 0), params.get("device_index", 0),
            params.get("parameter_index", None), params.get("parameter_name", None),
            params.get("value", 0.0))
        return result

    def _rd_get_master_device_parameters(self, params):
        response = {}
        response["result"] = self._get_master_device_parameters(params.get("device_index", 0))
        return response.get("result")

    def _rd_get_return_device_parameters(self, params):
        response = {}
        response["result"] = self._get_return_device_parameters(
            params.get("return_index", 0), params.get("device_index", 0))
        return response.get("result")

    def _wr_create_arrangement_midi_clip(self, params):
        result = None
        result = self._create_arrangement_midi_clip(
            params.get("track_index", 0),
            params.get("start_time", 0.0),
            params.get("length", 4.0),
            params.get("notes", []),
        )
        return result

    def _wr_create_midi_track(self, params):
        result = None
        index = params.get("index", -1)
        result = self._create_midi_track(index)
        return result

    def _wr_create_return_track(self, params):
        result = None
        result = self._create_return_track()
        return result

    def _wr_create_scene(self, params):
        result = None
        index = params.get("index", -1)
        result = self._create_scene(index)
        return result

    def _wr_delete_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._delete_clip(track_index, clip_index)
        return result

    def _wr_delete_device(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._delete_device(track_index, device_index)
        return result

    def _wr_delete_locator(self, params):
        result = None
        locator_index = params.get("locator_index", 0)
        result = self._delete_locator(locator_index)
        return result

    def _wr_delete_return_track(self, params):
        result = None
        index = params.get("index", 0)
        result = self._delete_return_track(index)
        return result

    def _wr_delete_scene(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        result = self._delete_scene(scene_index)
        return result

    def _wr_delete_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._delete_track(track_index)
        return result

    def _wr_delete_warp_marker(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        beat_time = params.get("beat_time", 0.0)
        result = self._delete_warp_marker(track_index, clip_index, beat_time)
        return result

    def _wr_deselect_all_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._deselect_all_notes(track_index, clip_index)
        return result

    def _wr_duplicate_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._duplicate_clip(track_index, clip_index)
        return result

    def _wr_duplicate_clip_loop(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._duplicate_clip_loop(track_index, clip_index)
        return result

    def _wr_duplicate_scene(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        result = self._duplicate_scene(scene_index)
        return result

    def _wr_duplicate_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._duplicate_track(track_index)
        return result

    def _wr_fire_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._fire_clip(track_index, clip_index)
        return result

    def _wr_fire_scene(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        result = self._fire_scene(scene_index)
        return result

    def _wr_flatten_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._flatten_track(track_index)
        return result

    def _wr_focus_view(self, params):
        result = None
        view_name = params.get("view_name", "Session")
        result = self._focus_view(view_name)
        return result

    def _wr_fold_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._fold_track(track_index, True)
        return result

    def _wr_freeze_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._freeze_track(track_index)
        return result

    def _wr_generate_bassline(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        root = params.get("root", 36)
        scale_type = params.get("scale_type", "minor")
        length = params.get("length", 4.0)
        result = self._generate_bassline(track_index, clip_index, root, scale_type, length)
        return result

    def _wr_generate_drum_pattern(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        style = params.get("style", "basic")
        length = params.get("length", 4.0)
        result = self._generate_drum_pattern(track_index, clip_index, style, length)
        return result

    def _wr_get_chain_device_parameters(self, params):
        result = None
        result = self._get_chain_device_parameters(
            params.get("track_index", 0), params.get("device_index", 0),
            params.get("chain_index", 0), params.get("chain_device_index", 0))
        return result

    def _wr_get_clip_automation(self, params):
        result = None
        result = self._get_clip_automation(
            params.get("track_index", 0), params.get("clip_index", 0),
            params.get("parameter_name", ""), params.get("device_index", None),
            params.get("samples", 33))
        return result

    def _wr_get_clip_warp_info(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._get_clip_warp_info(track_index, clip_index)
        return result

    def _wr_get_device_by_name(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_name = params.get("device_name", "")
        result = self._get_device_by_name(track_index, device_name)
        return result

    def _wr_get_groove_pool(self, params):
        result = None
        result = self._get_groove_pool()
        return result

    def _wr_get_rack_chains(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._get_rack_chains(track_index, device_index)
        return result

    def _wr_get_track_monitoring(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._get_track_monitoring(track_index)
        return result

    def _wr_humanize_clip_timing(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        amount = params.get("amount", 0.1)
        result = self._humanize_clip_timing(track_index, clip_index, amount)
        return result

    def _wr_humanize_clip_velocity(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        amount = params.get("amount", 0.1)
        result = self._humanize_clip_velocity(track_index, clip_index, amount)
        return result

    def _wr_jump_to_cue_point(self, params):
        result = None
        index = params.get("index", 0)
        result = self._jump_to_cue_point(index)
        return result

    def _wr_jump_to_next_cue(self, params):
        result = None
        result = self._jump_to_next_cue()
        return result

    def _wr_jump_to_prev_cue(self, params):
        result = None
        result = self._jump_to_prev_cue()
        return result

    def _wr_jump_to_time(self, params):
        result = None
        time = params.get("time", 0.0)
        result = self._jump_to_time(time)
        return result

    def _wr_load_browser_item(self, params):
        result = None
        track_index = params.get("track_index", 0)
        item_uri = params.get("item_uri", "")
        result = self._load_browser_item(track_index, item_uri)
        return result

    def _wr_load_browser_item_to_return(self, params):
        result = None
        return_index = params.get("return_index", 0)
        item_uri = params.get("item_uri", "")
        result = self._load_browser_item_to_return(return_index, item_uri)
        return result

    def _wr_load_device_preset(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        preset_uri = params.get("preset_uri", "")
        result = self._load_device_preset(track_index, device_index, preset_uri)
        return result

    def _wr_move_clip_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        time_delta = params.get("time_delta", 0)
        pitch_delta = params.get("pitch_delta", 0)
        result = self._move_clip_notes(track_index, clip_index, time_delta, pitch_delta)
        return result

    def _wr_move_device(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        new_index = params.get("new_index", 0)
        result = self._move_device(track_index, device_index, new_index)
        return result

    def _wr_move_device_left(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._move_device_left(track_index, device_index)
        return result

    def _wr_move_device_right(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._move_device_right(track_index, device_index)
        return result

    def _wr_quantize_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        quantize_to = params.get("quantize_to", 0.25)
        amount = params.get("amount", 1.0)
        result = self._quantize_clip(track_index, clip_index, quantize_to, amount)
        return result

    def _wr_quantize_clip_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        grid = params.get("grid", 0.25)
        result = self._quantize_clip_notes(track_index, clip_index, grid)
        return result

    def _wr_re_enable_automation(self, params):
        result = None
        result = self._re_enable_automation()
        return result

    def _wr_redo(self, params):
        result = None
        result = self._redo()
        return result

    def _wr_remove_all_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._remove_all_notes(track_index, clip_index)
        return result

    def _wr_remove_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        from_time = params.get("from_time", 0.0)
        time_span = params.get("time_span", 4.0)
        from_pitch = params.get("from_pitch", 0)
        pitch_span = params.get("pitch_span", 128)
        result = self._remove_notes(track_index, clip_index, from_time, time_span, from_pitch, pitch_span)
        return result

    def _wr_scrub_by(self, params):
        result = None
        delta = params.get("delta", 0)
        result = self._scrub_by(delta)
        return result

    def _wr_select_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._select_clip(track_index, clip_index)
        return result

    def _wr_select_device(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._select_device(track_index, device_index)
        return result

    def _wr_select_rack_chain(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        chain_index = params.get("chain_index", 0)
        result = self._select_rack_chain(track_index, device_index, chain_index)
        return result

    def _wr_select_scene(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        result = self._select_scene(scene_index)
        return result

    def _wr_select_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._select_track(track_index)
        return result

    def _wr_set_arrangement_loop(self, params):
        result = None
        start = params.get("start", 0.0)
        end = params.get("end", 4.0)
        enabled = params.get("enabled", True)
        result = self._set_arrangement_loop(start, end, enabled)
        return result

    def _wr_set_arrangement_overdub(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_arrangement_overdub(enabled)
        return result

    def _wr_set_chain_device_parameter(self, params):
        result = None
        result = self._set_chain_device_parameter(
            params.get("track_index", 0), params.get("device_index", 0),
            params.get("chain_index", 0), params.get("chain_device_index", 0),
            params.get("parameter_index", None), params.get("parameter_name", None),
            params.get("value", 0.0))
        return result

    def _wr_set_clip_automation(self, params):
        result = None
        result = self._set_clip_automation(
            params.get("track_index", 0), params.get("clip_index", 0),
            params.get("parameter_name", ""), params.get("envelope_data", []),
            params.get("device_index", None))
        return result

    def _wr_set_clip_color(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        color = params.get("color", 0)
        result = self._set_clip_color(track_index, clip_index, color)
        return result

    def _wr_set_clip_end_marker(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        position = params.get("position", 0)
        result = self._set_clip_end_marker(track_index, clip_index, position)
        return result

    def _wr_set_clip_end_time(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        time = params.get("time", 0)
        result = self._set_clip_end_time(track_index, clip_index, time)
        return result

    def _wr_set_clip_fade_in(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        start = params.get("start", 0)
        end = params.get("end", 0)
        result = self._set_clip_fade_in(track_index, clip_index, start, end)
        return result

    def _wr_set_clip_fade_out(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        start = params.get("start", 0)
        end = params.get("end", 0)
        result = self._set_clip_fade_out(track_index, clip_index, start, end)
        return result

    def _wr_set_clip_follow_action(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        action_a = params.get("action_a", None)
        action_b = params.get("action_b", None)
        chance = params.get("chance", None)
        time = params.get("time", None)
        result = self._set_clip_follow_action(track_index, clip_index, action_a, action_b, chance, time)
        return result

    def _wr_set_clip_gain(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        gain = params.get("gain", 0.0)  # dB
        result = self._set_clip_gain(track_index, clip_index, gain)
        return result

    def _wr_set_clip_launch_mode(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        mode = params.get("mode", 0)
        result = self._set_clip_launch_mode(track_index, clip_index, mode)
        return result

    def _wr_set_clip_launch_quantization(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        quantization = params.get("quantization", 0)
        result = self._set_clip_launch_quantization(track_index, clip_index, quantization)
        return result

    def _wr_set_clip_loop(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        loop_start = params.get("loop_start", 0.0)
        loop_end = params.get("loop_end", 4.0)
        looping = params.get("looping", True)
        result = self._set_clip_loop(track_index, clip_index, loop_start, loop_end, looping)
        return result

    def _wr_set_clip_name(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        name = params.get("name", "")
        result = self._set_clip_name(track_index, clip_index, name)
        return result

    def _wr_set_clip_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        notes = params.get("notes", [])
        result = self._set_clip_notes(track_index, clip_index, notes)
        return result

    def _wr_set_clip_pitch(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        pitch = params.get("pitch", 0)  # semitones
        result = self._set_clip_pitch(track_index, clip_index, pitch)
        return result

    def _wr_set_clip_ram_mode(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        enabled = params.get("enabled", False)
        result = self._set_clip_ram_mode(track_index, clip_index, enabled)
        return result

    def _wr_set_clip_start_marker(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        position = params.get("position", 0)
        result = self._set_clip_start_marker(track_index, clip_index, position)
        return result

    def _wr_set_clip_start_time(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        time = params.get("time", 0)
        result = self._set_clip_start_time(track_index, clip_index, time)
        return result

    def _wr_set_clip_trigger_quantization(self, params):
        result = None
        quant = params.get("quantization", 4)
        result = self._set_clip_trigger_quantization(quant)
        return result

    def _wr_set_clip_velocity_amount(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        amount = params.get("amount", 1.0)
        result = self._set_clip_velocity_amount(track_index, clip_index, amount)
        return result

    def _wr_set_clip_warp_mode(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        warp_mode = params.get("warp_mode", "beats")
        result = self._set_clip_warp_mode(track_index, clip_index, warp_mode)
        return result

    def _wr_set_count_in_duration(self, params):
        result = None
        duration = params.get("duration", 0)
        result = self._set_count_in_duration(duration)
        return result

    def _wr_set_crossfader(self, params):
        result = None
        value = params.get("value", 0.5)
        result = self._set_crossfader(value)
        return result

    def _wr_set_cue_volume(self, params):
        result = None
        volume = params.get("volume", 0.85)
        result = self._set_cue_volume(volume)
        return result

    def _wr_set_current_song_time(self, params):
        result = None
        time = params.get("time", 0)
        result = self._set_current_song_time(time)
        return result

    def _wr_set_detail_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._set_detail_clip(track_index, clip_index)
        return result

    def _wr_set_device_collapsed(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        collapsed = params.get("collapsed", False)
        result = self._set_device_collapsed(track_index, device_index, collapsed)
        return result

    def _wr_set_device_parameter(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        parameter_index = params.get("parameter_index", 0)
        value = params.get("value", 0.0)
        result = self._set_device_parameter(track_index, device_index, parameter_index, value)
        return result

    def _wr_set_draw_mode(self, params):
        result = None
        enabled = params.get("enabled", True)
        result = self._set_draw_mode(enabled)
        return result

    def _wr_set_drum_pad_name(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        pad_index = params.get("pad_index", 0)
        name = params.get("name", "")
        result = self._set_drum_pad_name(track_index, device_index, pad_index, name)
        return result

    def _wr_set_drum_rack_pad_mute(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        note = params.get("note", 36)
        mute = params.get("mute", False)
        result = self._set_drum_rack_pad_mute(track_index, device_index, note, mute)
        return result

    def _wr_set_drum_rack_pad_solo(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        note = params.get("note", 36)
        solo = params.get("solo", False)
        result = self._set_drum_rack_pad_solo(track_index, device_index, note, solo)
        return result

    def _wr_set_exclusive_arm(self, params):
        result = None
        enabled = params.get("enabled", True)
        result = self._set_exclusive_arm(enabled)
        return result

    def _wr_set_exclusive_solo(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_exclusive_solo(enabled)
        return result

    def _wr_set_follow_mode(self, params):
        result = None
        enabled = params.get("enabled", True)
        result = self._set_follow_mode(enabled)
        return result

    def _wr_set_grid_quantization(self, params):
        result = None
        quantization = params.get("quantization", 4)
        triplet = params.get("triplet", False)
        result = self._set_grid_quantization(quantization, triplet)
        return result

    def _wr_set_groove_amount(self, params):
        result = None
        amount = params.get("amount", 1.0)
        result = self._set_groove_amount(amount)
        return result

    def _wr_set_metronome(self, params):
        result = None
        enabled = params.get("enabled", True)
        result = self._set_metronome(enabled)
        return result

    def _wr_set_midi_recording_quantization(self, params):
        result = None
        quant = params.get("quantization", 0)
        result = self._set_midi_recording_quantization(quant)
        return result

    def _wr_set_overdub(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_overdub(enabled)
        return result

    def _wr_set_punch_in(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_punch_in(enabled)
        return result

    def _wr_set_punch_out(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_punch_out(enabled)
        return result

    def _wr_set_rack_macro(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        macro_index = params.get("macro_index", 0)
        value = params.get("value", 0.0)
        result = self._set_rack_macro(track_index, device_index, macro_index, value)
        return result

    def _wr_set_return_pan(self, params):
        result = None
        return_index = params.get("return_index", 0)
        pan = params.get("pan", 0.0)
        result = self._set_return_pan(return_index, pan)
        return result

    def _wr_set_return_volume(self, params):
        result = None
        return_index = params.get("return_index", 0)
        volume = params.get("volume", 0.85)
        result = self._set_return_volume(return_index, volume)
        return result

    def _wr_set_scene_color(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        color = params.get("color", 0)
        result = self._set_scene_color(scene_index, color)
        return result

    def _wr_set_scene_name(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        name = params.get("name", "")
        result = self._set_scene_name(scene_index, name)
        return result

    def _wr_set_send_level(self, params):
        result = None
        track_index = params.get("track_index", 0)
        send_index = params.get("send_index", 0)
        if "level" not in params:
            raise ValueError("set_send_level requires 'level' (got keys: %s). "
                             "Silently defaulting would set the send to 0.0 "
                             "and report success." % sorted(params.keys()))
        result = self._set_send_level(track_index, send_index, params["level"])
        return result

    def _wr_set_session_automation_record(self, params):
        result = None
        enabled = params.get("enabled", False)
        result = self._set_session_automation_record(enabled)
        return result

    def _wr_set_signature(self, params):
        result = None
        numerator = params.get("numerator", 4)
        denominator = params.get("denominator", 4)
        result = self._set_signature(numerator, denominator)
        return result

    def _wr_set_song_root_note(self, params):
        result = None
        root_note = params.get("root_note", 0)
        result = self._set_song_root_note(root_note)
        return result

    def _wr_set_song_scale(self, params):
        result = None
        result = self._set_song_scale(params.get("scale_name", None))
        return result

    def _wr_set_swing_amount(self, params):
        result = None
        amount = params.get("amount", 0.0)
        result = self._set_swing_amount(amount)
        return result

    def _wr_set_tempo(self, params):
        result = None
        tempo = params.get("tempo", 120.0)
        result = self._set_tempo(tempo)
        return result

    def _wr_set_track_arm(self, params):
        result = None
        track_index = params.get("track_index", 0)
        arm = params.get("arm", False)
        result = self._set_track_arm(track_index, arm)
        return result

    def _wr_set_track_color(self, params):
        result = None
        track_index = params.get("track_index", 0)
        color = params.get("color", 0)
        result = self._set_track_color(track_index, color)
        return result

    def _wr_set_track_crossfade_assign(self, params):
        result = None
        track_index = params.get("track_index", 0)
        assign = params.get("assign", 1)
        result = self._set_track_crossfade_assign(track_index, assign)
        return result

    def _wr_set_track_delay(self, params):
        result = None
        track_index = params.get("track_index", 0)
        delay_ms = params.get("delay_ms", 0)
        result = self._set_track_delay(track_index, delay_ms)
        return result

    def _wr_set_track_implicit_arm(self, params):
        result = None
        track_index = params.get("track_index", 0)
        enabled = params.get("enabled", False)
        result = self._set_track_implicit_arm(track_index, enabled)
        return result

    def _wr_set_track_input_routing(self, params):
        result = None
        track_index = params.get("track_index", 0)
        routing_type = params.get("routing_type", "")
        routing_channel = params.get("routing_channel", "")
        result = self._set_track_input_routing(track_index, routing_type, routing_channel)
        return result

    def _wr_set_track_monitoring(self, params):
        result = None
        track_index = params.get("track_index", 0)
        monitoring = params.get("monitoring", "auto")
        result = self._set_track_monitoring(track_index, monitoring)
        return result

    def _wr_set_track_mute(self, params):
        result = None
        track_index = params.get("track_index", 0)
        mute = params.get("mute", False)
        result = self._set_track_mute(track_index, mute)
        return result

    def _wr_set_track_name(self, params):
        result = None
        track_index = params.get("track_index", 0)
        name = params.get("name", "")
        result = self._set_track_name(track_index, name)
        return result

    def _wr_set_track_output_routing(self, params):
        result = None
        track_index = params.get("track_index", 0)
        routing_type = params.get("routing_type", "")
        routing_channel = params.get("routing_channel", "")
        result = self._set_track_output_routing(track_index, routing_type, routing_channel)
        return result

    def _wr_set_track_pan(self, params):
        result = None
        track_index = params.get("track_index", 0)
        if "pan" not in params:
            raise ValueError("set_track_pan requires 'pan' (got keys: %s). "
                             "Silently defaulting would centre the track and report success."
                             % sorted(params.keys()))
        result = self._set_track_pan(track_index, params["pan"])
        return result

    def _wr_set_track_solo(self, params):
        result = None
        track_index = params.get("track_index", 0)
        solo = params.get("solo", False)
        result = self._set_track_solo(track_index, solo)
        return result

    def _wr_set_track_volume(self, params):
        result = None
        track_index = params.get("track_index", 0)
        if "volume" not in params:
            raise ValueError("set_track_volume requires 'volume' (got keys: %s). "
                             "Silently defaulting would set 0.85 and report success."
                             % sorted(params.keys()))
        result = self._set_track_volume(track_index, params["volume"])
        return result

    def _wr_solo_exclusive(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._solo_exclusive(track_index)
        return result

    def _wr_start_playback(self, params):
        result = None
        result = self._start_playback()
        return result

    def _wr_start_recording(self, params):
        result = None
        result = self._start_recording()
        return result

    def _wr_stop_all_clips(self, params):
        result = None
        result = self._stop_all_clips()
        return result

    def _wr_stop_clip(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        result = self._stop_clip(track_index, clip_index)
        return result

    def _wr_stop_playback(self, params):
        result = None
        result = self._stop_playback()
        return result

    def _wr_stop_recording(self, params):
        result = None
        result = self._stop_recording()
        return result

    def _wr_stop_scene(self, params):
        result = None
        scene_index = params.get("scene_index", 0)
        result = self._stop_scene(scene_index)
        return result

    def _wr_tap_tempo(self, params):
        result = None
        result = self._tap_tempo()
        return result

    def _wr_toggle_arrangement_record(self, params):
        result = None
        result = self._toggle_arrangement_record()
        return result

    def _wr_toggle_device(self, params):
        result = None
        track_index = params.get("track_index", 0)
        device_index = params.get("device_index", 0)
        result = self._toggle_device(track_index, device_index)
        return result

    def _wr_toggle_session_record(self, params):
        result = None
        result = self._toggle_session_record()
        return result

    def _wr_transpose_notes(self, params):
        result = None
        track_index = params.get("track_index", 0)
        clip_index = params.get("clip_index", 0)
        semitones = params.get("semitones", 0)
        result = self._transpose_notes(track_index, clip_index, semitones)
        return result

    def _wr_trigger_back_to_arrangement(self, params):
        result = None
        result = self._trigger_back_to_arrangement()
        return result

    def _wr_unarm_all(self, params):
        result = None
        result = self._unarm_all()
        return result

    def _wr_undo(self, params):
        result = None
        result = self._undo()
        return result

    def _wr_unfold_track(self, params):
        result = None
        track_index = params.get("track_index", 0)
        result = self._fold_track(track_index, False)
        return result

    def _wr_ungroup_tracks(self, params):
        result = None
        group_track_index = params.get("group_track_index", 0)
        result = self._ungroup_tracks(group_track_index)
        return result

    def _wr_unmute_all(self, params):
        result = None
        result = self._unmute_all()
        return result

    def _wr_unsolo_all(self, params):
        result = None
        result = self._unsolo_all()
        return result

    
    # Command implementations

    def _describe_device_params(self, device):
        """Shared: list a device's parameters (matches get_device_parameters)."""
        out = []
        for i, param in enumerate(device.parameters):
            try:
                vstr = param.str_for_value(param.value)
            except Exception:
                vstr = None
            out.append({"index": i, "name": param.name, "value": param.value,
                        "value_string": vstr, "min": param.min, "max": param.max})
        return {"device_name": device.name, "parameter_count": len(out), "parameters": out}

    def _set_param_on(self, device, parameter_index, parameter_name, value):
        """Shared: set a parameter on an already-resolved device, by index or name."""
        ps = list(device.parameters)
        param = None
        if parameter_name is not None:
            for pp in ps:
                if pp.name.lower() == str(parameter_name).lower():
                    param = pp
                    break
            if param is None:
                return {"error": "No parameter '%s' on '%s'" % (parameter_name, device.name),
                        "available": [pp.name for pp in ps]}
        else:
            if parameter_index is None or parameter_index < 0 or parameter_index >= len(ps):
                return {"error": "Parameter index out of range (device has %d)" % len(ps)}
            param = ps[parameter_index]
        param.value = max(param.min, min(param.max, float(value)))
        return {"device_name": device.name, "parameter_name": param.name,
                "value": param.value, "min": param.min, "max": param.max}

    def _get_master_device_parameters(self, device_index):
        """Master-track device parameters. The Live API supports this fine; the
        old set_device_parameter just hardcoded self._song.tracks."""
        track = self._song.master_track
        if device_index < 0 or device_index >= len(track.devices):
            return {"error": "Device index out of range (master has %d)" % len(track.devices)}
        return self._describe_device_params(track.devices[device_index])

    def _set_master_device_parameter(self, device_index, parameter_index, parameter_name, value):
        track = self._song.master_track
        if device_index < 0 or device_index >= len(track.devices):
            return {"error": "Device index out of range (master has %d)" % len(track.devices)}
        return self._set_param_on(track.devices[device_index], parameter_index, parameter_name, value)

    def _get_return_device_parameters(self, return_index, device_index):
        rts = list(self._song.return_tracks)
        if return_index < 0 or return_index >= len(rts):
            return {"error": "Return index out of range (%d returns)" % len(rts)}
        track = rts[return_index]
        if device_index < 0 or device_index >= len(track.devices):
            return {"error": "Device index out of range (return has %d)" % len(track.devices)}
        return self._describe_device_params(track.devices[device_index])

    def _set_return_device_parameter(self, return_index, device_index, parameter_index, parameter_name, value):
        rts = list(self._song.return_tracks)
        if return_index < 0 or return_index >= len(rts):
            return {"error": "Return index out of range (%d returns)" % len(rts)}
        track = rts[return_index]
        if device_index < 0 or device_index >= len(track.devices):
            return {"error": "Device index out of range (return has %d)" % len(track.devices)}
        return self._set_param_on(track.devices[device_index], parameter_index, parameter_name, value)

    def _create_arrangement_midi_clip(self, track_index, start_time, length, notes=None):
        """Create a MIDI clip in the Arrangement view and optionally fill it.

        Session clips use clip_slot.create_clip(); the Arrangement view needs
        Track.create_midi_clip(start_time, length), added in Live 11. Written
        defensively because the exact signature has varied between versions.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if not hasattr(track, "create_midi_clip"):
                return {"error": "This Live version has no Track.create_midi_clip (needs Live 11+)"}
            if hasattr(track, "has_midi_input") and not track.has_midi_input:
                return {"error": "Track %d is not a MIDI track" % track_index}
            try:
                clip = track.create_midi_clip(start_time, length)
            except TypeError:
                clip = track.create_midi_clip(length)
            added = 0
            if notes and hasattr(clip, "add_new_notes"):
                import Live
                specs = []
                for n in notes:
                    kw = dict(pitch=int(n.get("pitch", 60)),
                              start_time=float(n.get("start_time", 0.0)),
                              duration=float(n.get("duration", 0.25)),
                              velocity=float(n.get("velocity", 100)),
                              mute=bool(n.get("mute", False)))
                    spec = None
                    if "probability" in n:
                        try:
                            spec = Live.Clip.MidiNoteSpecification(probability=float(n["probability"]), **kw)
                        except TypeError:
                            spec = None
                    if spec is None:
                        spec = Live.Clip.MidiNoteSpecification(**kw)
                    specs.append(spec)
                clip.add_new_notes(tuple(specs))
                added = len(specs)
            return {"created": True, "track_index": track_index,
                    "start_time": getattr(clip, "start_time", start_time),
                    "length": getattr(clip, "length", length),
                    "notes_added": added}
        except Exception as e:
            self.log_message("Error create_arrangement_midi_clip: " + str(e))
            return {"error": str(e)}


    # Validation helpers
    def _validate_track_index(self, track_index):
        """Validate track index and raise clear error if out of range"""
        if track_index < 0 or track_index >= len(self._song.tracks):
            raise IndexError(f"Track index {track_index} out of range (0-{len(self._song.tracks)-1})")
        return self._song.tracks[track_index]

    def _validate_clip_slot(self, track_index, clip_index):
        """Validate track and clip indices, return clip slot"""
        track = self._validate_track_index(track_index)
        if clip_index < 0 or clip_index >= len(track.clip_slots):
            raise IndexError(f"Clip index {clip_index} out of range (0-{len(track.clip_slots)-1})")
        return track.clip_slots[clip_index]

    def _validate_scene_index(self, scene_index):
        """Validate scene index and raise clear error if out of range"""
        if scene_index < 0 or scene_index >= len(self._song.scenes):
            raise IndexError(f"Scene index {scene_index} out of range (0-{len(self._song.scenes)-1})")
        return self._song.scenes[scene_index]

    def _validate_device_index(self, track, device_index):
        """Validate device index on a track"""
        if device_index < 0 or device_index >= len(track.devices):
            raise IndexError(f"Device index {device_index} out of range (0-{len(track.devices)-1})")
        return track.devices[device_index]

    def _validate_return_track_index(self, return_index):
        """Validate return track index"""
        if return_index < 0 or return_index >= len(self._song.return_tracks):
            raise IndexError(f"Return track index {return_index} out of range (0-{len(self._song.return_tracks)-1})")
        return self._song.return_tracks[return_index]

    def _validate_send_index(self, track, send_index):
        """Validate send index on a track"""
        sends = track.mixer_device.sends
        if send_index < 0 or send_index >= len(sends):
            raise IndexError(f"Send index {send_index} out of range (0-{len(sends)-1})")
        return sends[send_index]

    def _clamp_volume(self, value):
        """Clamp volume to valid range 0.0-1.0"""
        return max(0.0, min(1.0, float(value)))

    def _clamp_pan(self, value):
        """Clamp pan to valid range -1.0 to 1.0"""
        return max(-1.0, min(1.0, float(value)))

    # =====================================================
    # Master Track Methods
    # =====================================================

    def _set_master_volume(self, volume):
        """Set master track volume (0.0 to 1.0)"""
        try:
            volume = self._clamp_volume(volume)
            self._song.master_track.mixer_device.volume.value = volume
            return {
                "volume": self._song.master_track.mixer_device.volume.value,
                "success": True
            }
        except Exception as e:
            self.log_message("Error setting master volume: " + str(e))
            raise

    def _set_master_pan(self, pan):
        """Set master track pan (-1.0 to 1.0)"""
        try:
            pan = self._clamp_pan(pan)
            self._song.master_track.mixer_device.panning.value = pan
            return {
                "panning": self._song.master_track.mixer_device.panning.value,
                "success": True
            }
        except Exception as e:
            self.log_message("Error setting master pan: " + str(e))
            raise

    def _get_master_info(self):
        """Get master track info including devices"""
        try:
            master = self._song.master_track
            devices = []
            for i, device in enumerate(master.devices):
                devices.append({
                    "index": i,
                    "name": device.name,
                    "class_name": device.class_name,
                    "is_active": device.is_active
                })

            return {
                "name": "Master",
                "volume": master.mixer_device.volume.value,
                "panning": master.mixer_device.panning.value,
                "device_count": len(master.devices),
                "devices": devices
            }
        except Exception as e:
            self.log_message("Error getting master info: " + str(e))
            raise

    # =====================================================
    # Browser Methods
    # =====================================================

    def _browse_path(self, path_list):
        """Navigate browser by path list e.g. ['Sounds', 'Bass', 'Sub Bass']"""
        try:
            app = self.application()
            browser = app.browser

            # Map category names to browser attributes (case-insensitive)
            category_map = {
                "instruments": browser.instruments,
                "sounds": browser.sounds,
                "drums": browser.drums,
                "audio_effects": browser.audio_effects,
                "midi_effects": browser.midi_effects,
            }

            # Add samples and packs if available
            if hasattr(browser, 'samples'):
                category_map["samples"] = browser.samples
            if hasattr(browser, 'packs'):
                category_map["packs"] = browser.packs

            if not path_list:
                # Return available categories
                return {
                    "path": [],
                    "available_categories": list(category_map.keys()),
                    "items": []
                }

            # Get starting category (normalize to lowercase with underscores)
            category = path_list[0].lower().replace(" ", "_")
            if category not in category_map:
                return {
                    "error": "Unknown category: {0}".format(category),
                    "available_categories": list(category_map.keys())
                }

            current = category_map[category]

            # Navigate through remaining path parts
            for i in range(1, len(path_list)):
                part = path_list[i]
                found = False
                if hasattr(current, 'children'):
                    for child in current.children:
                        if child.name.lower() == part.lower():
                            current = child
                            found = True
                            break
                if not found:
                    return {
                        "error": "Path part '{0}' not found".format(part),
                        "path": path_list[:i]
                    }

            # Return children of current item
            items = []
            if hasattr(current, 'children'):
                for child in current.children:
                    items.append({
                        "name": child.name,
                        "is_folder": child.is_folder if hasattr(child, 'is_folder') else False,
                        "is_device": child.is_device if hasattr(child, 'is_device') else False,
                        "is_loadable": child.is_loadable if hasattr(child, 'is_loadable') else False,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    })

            return {
                "path": path_list,
                "items": items,
                "item_count": len(items)
            }
        except Exception as e:
            self.log_message("Error browsing path: " + str(e))
            raise

    def _get_browser_children(self, uri):
        """Get children of browser item by URI"""
        try:
            app = self.application()
            browser = app.browser

            # Find item by URI
            item = self._find_browser_item_by_uri(browser, uri)
            if not item:
                return {"error": "Item not found: {0}".format(uri)}

            children = []
            if hasattr(item, 'children'):
                for child in item.children:
                    children.append({
                        "name": child.name,
                        "is_folder": child.is_folder if hasattr(child, 'is_folder') else False,
                        "is_device": child.is_device if hasattr(child, 'is_device') else False,
                        "is_loadable": child.is_loadable if hasattr(child, 'is_loadable') else False,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    })

            return {
                "uri": uri,
                "name": item.name if hasattr(item, 'name') else "Unknown",
                "children": children,
                "child_count": len(children)
            }
        except Exception as e:
            self.log_message("Error getting browser children: " + str(e))
            raise

    def _search_browser(self, query, category="all"):
        """Search browser for items matching query"""
        try:
            app = self.application()
            browser = app.browser

            results = []
            query_lower = query.lower()

            # Determine which categories to search
            categories_to_search = []
            if category == "all":
                categories_to_search = [
                    ("instruments", browser.instruments),
                    ("sounds", browser.sounds),
                    ("drums", browser.drums),
                    ("audio_effects", browser.audio_effects),
                    ("midi_effects", browser.midi_effects)
                ]
            elif category == "instruments":
                categories_to_search = [("instruments", browser.instruments)]
            elif category == "sounds":
                categories_to_search = [("sounds", browser.sounds)]
            elif category == "drums":
                categories_to_search = [("drums", browser.drums)]
            elif category == "audio_effects":
                categories_to_search = [("audio_effects", browser.audio_effects)]
            elif category == "midi_effects":
                categories_to_search = [("midi_effects", browser.midi_effects)]
            else:
                return {"error": "Unknown category: {0}".format(category)}

            def search_recursive(item, cat_name, depth=0):
                if depth > 4:  # Limit depth for performance
                    return
                if len(results) >= 50:  # Limit results
                    return

                # Check if item name matches query
                if hasattr(item, 'name') and query_lower in item.name.lower():
                    is_loadable = item.is_loadable if hasattr(item, 'is_loadable') else False
                    results.append({
                        "name": item.name,
                        "category": cat_name,
                        "uri": item.uri if hasattr(item, 'uri') else None,
                        "is_loadable": is_loadable,
                        "is_device": item.is_device if hasattr(item, 'is_device') else False
                    })

                # Recurse into children
                if hasattr(item, 'children') and (item.is_folder if hasattr(item, 'is_folder') else True):
                    for child in item.children:
                        search_recursive(child, cat_name, depth + 1)
                        if len(results) >= 50:
                            break

            for cat_name, cat_item in categories_to_search:
                if hasattr(cat_item, 'children'):
                    for child in cat_item.children:
                        search_recursive(child, cat_name)
                        if len(results) >= 50:
                            break

            return {
                "query": query,
                "category": category,
                "results": results,
                "result_count": len(results)
            }
        except Exception as e:
            self.log_message("Error searching browser: " + str(e))
            raise

    def _load_instrument_or_effect(self, track_index, uri):
        """Load an instrument or effect onto a track by URI"""
        try:
            track = self._validate_track_index(track_index)

            app = self.application()
            browser = app.browser

            # Find the browser item by URI
            item = self._find_browser_item_by_uri(browser, uri)

            if not item:
                return {"error": "Browser item not found: {0}".format(uri)}

            if not (item.is_loadable if hasattr(item, 'is_loadable') else False):
                return {"error": "Item is not loadable: {0}".format(item.name)}

            # Select the track so the item loads onto it
            self._song.view.selected_track = track

            # Load the item
            browser.load_item(item)

            return {
                "loaded": True,
                "item_name": item.name,
                "track_index": track_index,
                "track_name": track.name,
                "uri": uri
            }
        except Exception as e:
            self.log_message("Error loading instrument/effect: " + str(e))
            raise

    def _load_browser_item_to_return(self, return_index, item_uri):
        """Load a browser item onto a return track"""
        try:
            return_track = self._validate_return_track_index(return_index)

            app = self.application()
            browser = app.browser

            # Find the browser item by URI
            item = self._find_browser_item_by_uri(browser, item_uri)

            if not item:
                return {"error": "Browser item not found: {0}".format(item_uri)}

            if not (item.is_loadable if hasattr(item, 'is_loadable') else False):
                return {"error": "Item is not loadable: {0}".format(item.name)}

            # Select the return track
            self._song.view.selected_track = return_track

            # Load the item
            browser.load_item(item)

            return {
                "loaded": True,
                "item_name": item.name,
                "return_index": return_index,
                "return_track_name": return_track.name,
                "uri": item_uri
            }
        except Exception as e:
            self.log_message("Error loading item to return track: " + str(e))
            raise

    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            self._song.create_audio_track(index)
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]

            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    def _health_check(self):
        """Check if Ableton is responsive"""
        try:
            result = {
                "status": "ok",
                "tempo": self._song.tempo,
                "is_playing": self._song.is_playing,
                "track_count": len(self._song.tracks)
            }
            return result
        except Exception as e:
            self.log_message("Error in health check: " + str(e))
            raise

    def _get_playback_position(self):
        """Get the current playback position"""
        try:
            result = {
                "current_song_time": self._song.current_song_time,
                "is_playing": self._song.is_playing,
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator
            }
            return result
        except Exception as e:
            self.log_message("Error getting playback position: " + str(e))
            raise

    def _set_track_mute(self, track_index, mute):
        """Set the mute state of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.mute = mute

            result = {
                "track_index": track_index,
                "mute": track.mute
            }
            return result
        except Exception as e:
            self.log_message("Error setting track mute: " + str(e))
            raise

    def _set_track_solo(self, track_index, solo):
        """Set the solo state of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.solo = solo

            result = {
                "track_index": track_index,
                "solo": track.solo
            }
            return result
        except Exception as e:
            self.log_message("Error setting track solo: " + str(e))
            raise

    def _set_track_arm(self, track_index, arm):
        """Set the arm (record enable) state of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            if track.can_be_armed:
                track.arm = arm
                result = {
                    "track_index": track_index,
                    "arm": track.arm
                }
            else:
                result = {
                    "track_index": track_index,
                    "arm": False,
                    "error": "Track cannot be armed"
                }
            return result
        except Exception as e:
            self.log_message("Error setting track arm: " + str(e))
            raise

    def _set_track_volume(self, track_index, volume):
        """Set the volume of a track (0.0 to 1.0)"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.mixer_device.volume.value = max(0.0, min(1.0, volume))

            result = {
                "track_index": track_index,
                "volume": track.mixer_device.volume.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_pan(self, track_index, pan):
        """Set the panning of a track (-1.0 to 1.0)"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            track.mixer_device.panning.value = max(-1.0, min(1.0, pan))

            result = {
                "track_index": track_index,
                "panning": track.mixer_device.panning.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting track pan: " + str(e))
            raise

    def _get_clip_notes(self, track_index, clip_index):
        """Get all notes from a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            # Get all notes from the clip
            # select_all_notes selects all notes, get_selected_notes returns them
            clip.select_all_notes()
            notes_data = clip.get_selected_notes()
            clip.deselect_all_notes()

            notes = []
            for note in notes_data:
                notes.append({
                    "pitch": note[0],
                    "start_time": note[1],
                    "duration": note[2],
                    "velocity": note[3],
                    "mute": note[4]
                })

            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip.name,
                "length": clip.length,
                "note_count": len(notes),
                "notes": notes
            }
            return result
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _get_clip_info(self, track_index, clip_index):
        """Get clip metadata without notes"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)

            if not clip_slot.has_clip:
                return {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "has_clip": False
                }

            clip = clip_slot.clip

            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "has_clip": True,
                "name": clip.name,
                "length": clip.length,
                "is_midi_clip": clip.is_midi_clip,
                "is_audio_clip": clip.is_audio_clip,
                "is_playing": clip.is_playing,
                "is_recording": clip.is_recording,
                "is_triggered": clip.is_triggered,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "start_marker": clip.start_marker,
                "end_marker": clip.end_marker,
                "color_index": clip.color_index
            }

            # Add warp mode for audio clips
            if clip.is_audio_clip:
                result["warping"] = clip.warping
                result["warp_mode"] = clip.warp_mode if hasattr(clip, 'warp_mode') else None

            return result
        except Exception as e:
            self.log_message("Error getting clip info: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete a clip from a clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip_name = clip_slot.clip.name
            clip_slot.delete_clip()

            result = {
                "deleted": True,
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip_name
            }
            return result
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _get_device_parameters(self, track_index, device_index):
        """Get all parameters from a device"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")

            device = track.devices[device_index]

            parameters = []
            for i, param in enumerate(device.parameters):
                # value_string is what Live PRINTS on the knob ("Off", "1/16", "440 Hz").
                # Without it a caller only sees a bare float and cannot tell what
                # "Transpose Mode = 0.0" actually means.
                try:
                    vstr = param.str_for_value(param.value)
                except Exception:
                    vstr = None
                param_info = {
                    "index": i,
                    "name": param.name,
                    "value": param.value,
                    "value_string": vstr,
                    "min": param.min,
                    "max": param.max,
                    "is_enabled": param.is_enabled,
                    "is_quantized": param.is_quantized
                }
                if param.is_quantized:
                    param_info["value_items"] = list(param.value_items) if hasattr(param, 'value_items') else []
                parameters.append(param_info)

            result = {
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device.name,
                "device_class": device.class_name,
                "parameter_count": len(parameters),
                "parameters": parameters
            }
            return result
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set a device parameter value"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")

            device = track.devices[device_index]

            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range")

            param = device.parameters[parameter_index]

            if not param.is_enabled:
                raise Exception("Parameter is not enabled")

            # Clamp value to valid range
            clamped_value = max(param.min, min(param.max, value))
            param.value = clamped_value

            result = {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": parameter_index,
                "parameter_name": param.name,
                "value": param.value,
                "min": param.min,
                "max": param.max
            }
            return result
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise

    def _get_song_scale_names(self):
        """Scale names Live actually accepts, so callers do not have to guess."""
        try:
            names = list(getattr(self._song, "available_scale_names", []) or [])
            return {"current": getattr(self._song, "scale_name", None),
                    "root_note": getattr(self._song, "root_note", None),
                    "available": [str(n) for n in names], "count": len(names)}
        except Exception as e:
            return {"error": str(e)}

    def _set_song_scale(self, scale_name):
        """Set the song scale. get_song_scale existed with no setter, so the
        global scale was readable but unchangeable."""
        try:
            if not scale_name:
                return {"error": "scale_name is required"}
            avail = [str(n) for n in (getattr(self._song, "available_scale_names", []) or [])]
            target = None
            for n in avail:
                if n.lower() == str(scale_name).lower():
                    target = n
                    break
            if target is None:
                return {"error": "Unknown scale '%s'" % scale_name, "available": avail}
            self._song.scale_name = target
            return {"scale_name": self._song.scale_name,
                    "root_note": getattr(self._song, "root_note", None)}
        except Exception as e:
            self.log_message("Error set_song_scale: " + str(e))
            return {"error": str(e)}

    def _find_track_param(self, track, parameter_name, device_index=None):
        """Resolve a parameter name on a track, unambiguously.

        Searching every device and taking the FIRST hit silently targets the wrong
        device whenever a name is shared - and names are shared constantly
        ("Frequency" lives on Auto Filter, Erosion, Reverb, Grain Delay...).
        Pass device_index to scope it. Without it, an ambiguous name raises
        rather than guessing.
        """
        name = str(parameter_name).lower()

        mixer = track.mixer_device
        if device_index is None:
            if name == "volume":
                return mixer.volume, "Mixer"
            if name in ("pan", "panning"):
                return mixer.panning, "Mixer"

        if device_index is not None:
            devs = list(track.devices)
            if device_index < 0 or device_index >= len(devs):
                raise IndexError("Device index out of range (track has %d)" % len(devs))
            dev = devs[device_index]
            for p in dev.parameters:
                if p.name.lower() == name:
                    return p, dev.name
            raise ValueError("No parameter '%s' on device '%s'. Available: %s"
                             % (parameter_name, dev.name, [p.name for p in dev.parameters][:25]))

        matches = [(d, p) for d in track.devices for p in d.parameters if p.name.lower() == name]
        if not matches:
            raise ValueError("Parameter not found: %s" % parameter_name)
        if len(matches) > 1:
            raise ValueError("Ambiguous parameter '%s' found on %d devices: %s. "
                             "Pass device_index to disambiguate."
                             % (parameter_name, len(matches), [d.name for d, _ in matches]))
        return matches[0][1], matches[0][0].name

    def _resolve_chain_device(self, track_index, device_index, chain_index, chain_device_index):
        """Walk track -> rack -> chain -> device. Racks hide their contents from
        get_device_parameters, which only ever returns the rack's own macros."""
        track = self._validate_track_index(track_index)
        device = self._validate_device_index(track, device_index)
        if not device.can_have_chains:
            raise ValueError("Device '%s' is not a rack" % device.name)
        chains = list(device.chains)
        if chain_index < 0 or chain_index >= len(chains):
            raise IndexError("Chain index out of range (rack has %d)" % len(chains))
        chain = chains[chain_index]
        devs = list(chain.devices)
        if chain_device_index < 0 or chain_device_index >= len(devs):
            raise IndexError("Chain device index out of range (chain has %d)" % len(devs))
        return chain, devs[chain_device_index]

    def _get_chain_device_parameters(self, track_index, device_index, chain_index, chain_device_index):
        """Parameters of a device nested inside a rack chain (e.g. a drum pad's synth)."""
        try:
            chain, dev = self._resolve_chain_device(track_index, device_index, chain_index, chain_device_index)
            out = []
            for i, p in enumerate(dev.parameters):
                try:
                    vstr = p.str_for_value(p.value)
                except Exception:
                    vstr = None
                out.append({"index": i, "name": p.name, "value": p.value,
                            "value_string": vstr, "min": p.min, "max": p.max,
                            "is_quantized": bool(getattr(p, "is_quantized", False))})
            return {"chain_name": chain.name, "device_name": dev.name,
                    "parameter_count": len(out), "parameters": out}
        except Exception as e:
            self.log_message("Error get_chain_device_parameters: " + str(e))
            return {"error": str(e)}

    def _set_chain_device_parameter(self, track_index, device_index, chain_index,
                                    chain_device_index, parameter_index, parameter_name, value):
        """Set a parameter on a device nested inside a rack chain. Accepts an index
        or a name; name is resolved within THIS device only, so it cannot grab a
        same-named parameter from some other device the way clip automation does."""
        try:
            chain, dev = self._resolve_chain_device(track_index, device_index, chain_index, chain_device_index)
            ps = list(dev.parameters)
            param = None
            if parameter_name is not None:
                for p in ps:
                    if p.name.lower() == str(parameter_name).lower():
                        param = p; break
                if param is None:
                    return {"error": "No parameter '%s' on '%s'" % (parameter_name, dev.name),
                            "available": [p.name for p in ps]}
            else:
                if parameter_index is None or parameter_index < 0 or parameter_index >= len(ps):
                    return {"error": "Parameter index out of range (device has %d)" % len(ps)}
                param = ps[parameter_index]
            v = max(param.min, min(param.max, float(value)))
            param.value = v
            return {"chain_name": chain.name, "device_name": dev.name,
                    "parameter_name": param.name, "value": param.value,
                    "min": param.min, "max": param.max}
        except Exception as e:
            self.log_message("Error set_chain_device_parameter: " + str(e))
            return {"error": str(e)}

    def _add_notes_with_probability(self, track_index, clip_index, notes, replace=True):
        """Add MIDI notes carrying per-note probability.

        The rest of this script uses clip.set_notes() with 5-tuples, which cannot
        express probability. Live 11+ exposes MidiNoteSpecification via
        clip.add_new_notes(), which can.
        """
        try:
            import Live

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip

            if not hasattr(clip, "add_new_notes"):
                return {"error": "add_new_notes unavailable - Live 11+ required"}

            if replace and hasattr(clip, "remove_notes_extended"):
                clip.remove_notes_extended(0, 128, 0.0, clip.length)

            specs = []
            for note in notes:
                kwargs = dict(
                    pitch=int(note.get("pitch", 60)),
                    start_time=float(note.get("start_time", 0.0)),
                    duration=float(note.get("duration", 0.25)),
                    velocity=float(note.get("velocity", 100)),
                    mute=bool(note.get("mute", False)),
                )
                spec = None
                if "probability" in note:
                    try:
                        spec = Live.Clip.MidiNoteSpecification(
                            probability=float(note["probability"]), **kwargs)
                    except TypeError:
                        spec = None
                if spec is None:
                    spec = Live.Clip.MidiNoteSpecification(**kwargs)
                    if "probability" in note and hasattr(spec, "probability"):
                        spec.probability = float(note["probability"])
                if "velocity_deviation" in note and hasattr(spec, "velocity_deviation"):
                    spec.velocity_deviation = float(note["velocity_deviation"])
                specs.append(spec)

            clip.add_new_notes(tuple(specs))

            # Read one note back so the caller can verify probability really landed.
            probe = None
            if hasattr(clip, "get_notes_extended"):
                got = clip.get_notes_extended(0, 128, 0.0, clip.length)
                if len(got):
                    probe = {"pitch": got[0].pitch, "probability": getattr(got[0], "probability", None)}

            return {"note_count": len(specs), "verified_first_note": probe}
        except Exception as e:
            self.log_message("Error add_notes_with_probability: " + str(e))
            raise

    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()

            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise

    # ==================== SCENE MANAGEMENT ====================

    def _get_all_scenes(self):
        """Get information about all scenes"""
        try:
            scenes = []
            for i, scene in enumerate(self._song.scenes):
                scene_info = {
                    "index": i,
                    "name": scene.name,
                    "color": scene.color if hasattr(scene, 'color') else None,
                    "color_index": scene.color_index if hasattr(scene, 'color_index') else None,
                    "is_triggered": scene.is_triggered if hasattr(scene, 'is_triggered') else False,
                    "tempo": scene.tempo if hasattr(scene, 'tempo') else None,
                }
                scenes.append(scene_info)

            result = {
                "scene_count": len(scenes),
                "scenes": scenes
            }
            return result
        except Exception as e:
            self.log_message("Error getting all scenes: " + str(e))
            raise

    def _create_scene(self, index):
        """Create a new scene at the specified index"""
        try:
            self._song.create_scene(index)
            new_index = len(self._song.scenes) - 1 if index == -1 else index
            new_scene = self._song.scenes[new_index]

            result = {
                "index": new_index,
                "name": new_scene.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _delete_scene(self, scene_index):
        """Delete a scene at the specified index"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            scene_name = self._song.scenes[scene_index].name
            self._song.delete_scene(scene_index)

            result = {
                "deleted": True,
                "scene_index": scene_index,
                "scene_name": scene_name
            }
            return result
        except Exception as e:
            self.log_message("Error deleting scene: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Fire (trigger) a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            scene = self._song.scenes[scene_index]
            scene.fire()

            result = {
                "fired": True,
                "scene_index": scene_index,
                "scene_name": scene.name
            }
            return result
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    def _stop_scene(self, scene_index):
        """Stop all clips in a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            # Stop all clip slots in this scene row
            for track in self._song.tracks:
                if scene_index < len(track.clip_slots):
                    track.clip_slots[scene_index].stop()

            result = {
                "stopped": True,
                "scene_index": scene_index
            }
            return result
        except Exception as e:
            self.log_message("Error stopping scene: " + str(e))
            raise

    def _set_scene_name(self, scene_index, name):
        """Set the name of a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            scene = self._song.scenes[scene_index]
            scene.name = name

            result = {
                "scene_index": scene_index,
                "name": scene.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting scene name: " + str(e))
            raise

    def _set_scene_color(self, scene_index, color):
        """Set the color of a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            scene = self._song.scenes[scene_index]
            if hasattr(scene, 'color_index'):
                scene.color_index = color

            result = {
                "scene_index": scene_index,
                "color_index": scene.color_index if hasattr(scene, 'color_index') else None
            }
            return result
        except Exception as e:
            self.log_message("Error setting scene color: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        """Duplicate a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            self._song.duplicate_scene(scene_index)
            new_index = scene_index + 1

            result = {
                "duplicated": True,
                "original_index": scene_index,
                "new_index": new_index,
                "new_name": self._song.scenes[new_index].name
            }
            return result
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    # ==================== TRACK MANAGEMENT ====================

    def _delete_track(self, track_index):
        """Delete a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track_name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)

            result = {
                "deleted": True,
                "track_index": track_index,
                "track_name": track_name
            }
            return result
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _duplicate_track(self, track_index):
        """Duplicate a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            self._song.duplicate_track(track_index)
            new_index = track_index + 1

            result = {
                "duplicated": True,
                "original_index": track_index,
                "new_index": new_index,
                "new_name": self._song.tracks[new_index].name
            }
            return result
        except Exception as e:
            self.log_message("Error duplicating track: " + str(e))
            raise

    def _set_track_color(self, track_index, color):
        """Set the color of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            if hasattr(track, 'color_index'):
                track.color_index = color

            result = {
                "track_index": track_index,
                "color_index": track.color_index if hasattr(track, 'color_index') else None
            }
            return result
        except Exception as e:
            self.log_message("Error setting track color: " + str(e))
            raise

    # ==================== DEVICE MANAGEMENT ====================

    def _toggle_device(self, track_index, device_index):
        """Toggle a device on/off"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")

            device = track.devices[device_index]

            # Toggle the device on/off via the first parameter (Device On)
            if len(device.parameters) > 0:
                on_param = device.parameters[0]  # First param is usually "Device On"
                if on_param.name == "Device On":
                    on_param.value = 0.0 if on_param.value > 0.5 else 1.0

            result = {
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device.name,
                "is_active": device.parameters[0].value > 0.5 if len(device.parameters) > 0 else True
            }
            return result
        except Exception as e:
            self.log_message("Error toggling device: " + str(e))
            raise

    def _delete_device(self, track_index, device_index):
        """Delete a device from a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")

            device_name = track.devices[device_index].name
            track.delete_device(device_index)

            result = {
                "deleted": True,
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device_name
            }
            return result
        except Exception as e:
            self.log_message("Error deleting device: " + str(e))
            raise

    # ==================== CLIP MANAGEMENT ====================

    def _duplicate_clip(self, track_index, clip_index):
        """Duplicate a clip to the next empty slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            # Find next empty slot
            target_index = None
            for i in range(clip_index + 1, len(track.clip_slots)):
                if not track.clip_slots[i].has_clip:
                    target_index = i
                    break

            if target_index is None:
                raise Exception("No empty slot available for duplication")

            clip_slot.duplicate_clip_to(track.clip_slots[target_index])

            result = {
                "duplicated": True,
                "original_index": clip_index,
                "new_index": target_index,
                "clip_name": track.clip_slots[target_index].clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error duplicating clip: " + str(e))
            raise

    def _set_clip_color(self, track_index, clip_index, color):
        """Set the color of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip
            if hasattr(clip, 'color_index'):
                clip.color_index = color

            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "color_index": clip.color_index if hasattr(clip, 'color_index') else None
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip color: " + str(e))
            raise

    def _set_clip_loop(self, track_index, clip_index, loop_start, loop_end, looping):
        """Set the loop settings of a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip
            clip.looping = looping
            clip.loop_start = loop_start
            clip.loop_end = loop_end

            result = {
                "track_index": track_index,
                "clip_index": clip_index,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip loop: " + str(e))
            raise

    # ==================== NOTE EDITING ====================

    def _remove_notes(self, track_index, clip_index, from_time, time_span, from_pitch, pitch_span):
        """Remove notes from a clip within a range"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            clip.remove_notes(from_time, from_pitch, time_span, pitch_span)

            result = {
                "removed": True,
                "track_index": track_index,
                "clip_index": clip_index,
                "from_time": from_time,
                "time_span": time_span,
                "from_pitch": from_pitch,
                "pitch_span": pitch_span
            }
            return result
        except Exception as e:
            self.log_message("Error removing notes: " + str(e))
            raise

    def _remove_all_notes(self, track_index, clip_index):
        """Remove all notes from a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            clip.remove_notes(0, 0, clip.length, 128)

            result = {
                "removed": True,
                "track_index": track_index,
                "clip_index": clip_index
            }
            return result
        except Exception as e:
            self.log_message("Error removing all notes: " + str(e))
            raise

    def _transpose_notes(self, track_index, clip_index, semitones):
        """Transpose all notes in a clip, PRESERVING probability.

        The previous implementation round-tripped through clip.set_notes() with
        5-tuples (pitch, start, duration, velocity, mute). That tuple has no
        probability field, so every transpose silently wiped per-note probability.
        Use the extended API when Live offers it and fall back only if it does not.
        """
        try:
            track = self._song.tracks[track_index]
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip

            if hasattr(clip, "get_notes_extended") and hasattr(clip, "add_new_notes"):
                import Live
                notes = list(clip.get_notes_extended(0, 128, 0.0, clip.length))
                specs, preserved = [], 0
                for nt in notes:
                    kw = dict(pitch=max(0, min(127, nt.pitch + semitones)),
                              start_time=nt.start_time, duration=nt.duration,
                              velocity=nt.velocity, mute=nt.mute)
                    prob = getattr(nt, "probability", None)
                    spec = None
                    if prob is not None:
                        if prob < 1.0:
                            preserved += 1
                        try:
                            spec = Live.Clip.MidiNoteSpecification(probability=prob, **kw)
                        except TypeError:
                            spec = None
                    if spec is None:
                        spec = Live.Clip.MidiNoteSpecification(**kw)
                        if prob is not None and hasattr(spec, "probability"):
                            spec.probability = prob
                    vd = getattr(nt, "velocity_deviation", None)
                    if vd is not None and hasattr(spec, "velocity_deviation"):
                        spec.velocity_deviation = vd
                    specs.append(spec)
                clip.remove_notes_extended(0, 128, 0.0, clip.length)
                clip.add_new_notes(tuple(specs))
                return {"transposed": len(specs), "semitones": semitones,
                        "probability_preserved": True,
                        "notes_with_probability_below_1": preserved}

            # legacy fallback - cannot carry probability
            notes = clip.get_notes(0, 0, clip.length, 128)
            out = tuple((max(0, min(127, n[0] + semitones)), n[1], n[2], n[3], n[4]) for n in notes)
            clip.set_notes(out)
            return {"transposed": len(out), "semitones": semitones,
                    "probability_preserved": False,
                    "warning": "Live lacks the extended note API; probability was lost."}
        except Exception as e:
            self.log_message("Error transposing notes: " + str(e))
            raise
    def _undo(self):
        """Undo the last operation"""
        try:
            if self._song.can_undo:
                self._song.undo()
                result = {
                    "undone": True
                }
            else:
                result = {
                    "undone": False,
                    "error": "Nothing to undo"
                }
            return result
        except Exception as e:
            self.log_message("Error undoing: " + str(e))
            raise

    def _redo(self):
        """Redo the last undone operation"""
        try:
            if self._song.can_redo:
                self._song.redo()
                result = {
                    "redone": True
                }
            else:
                result = {
                    "redone": False,
                    "error": "Nothing to redo"
                }
            return result
        except Exception as e:
            self.log_message("Error redoing: " + str(e))
            raise

    # ==================== RETURN/SEND TRACK CONTROL ====================

    def _get_return_tracks(self):
        """Get information about all return tracks"""
        try:
            return_tracks = []
            for i, track in enumerate(self._song.return_tracks):
                track_info = {
                    "index": i,
                    "name": track.name,
                    "color_index": track.color_index if hasattr(track, 'color_index') else None,
                    "mute": track.mute,
                    "solo": track.solo,
                    "volume": track.mixer_device.volume.value,
                    "panning": track.mixer_device.panning.value,
                    "device_count": len(track.devices)
                }
                return_tracks.append(track_info)

            result = {
                "return_track_count": len(return_tracks),
                "return_tracks": return_tracks
            }
            return result
        except Exception as e:
            self.log_message("Error getting return tracks: " + str(e))
            raise

    def _get_return_track_info(self, return_index):
        """Get detailed information about a return track"""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")

            track = self._song.return_tracks[return_index]

            devices = []
            for i, device in enumerate(track.devices):
                devices.append({
                    "index": i,
                    "name": device.name,
                    "class_name": device.class_name
                })

            result = {
                "index": return_index,
                "name": track.name,
                "color_index": track.color_index if hasattr(track, 'color_index') else None,
                "mute": track.mute,
                "solo": track.solo,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting return track info: " + str(e))
            raise

    def _set_send_level(self, track_index, send_index, level):
        """Set the send level from a track to a return track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            sends = track.mixer_device.sends

            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index out of range")

            sends[send_index].value = max(0.0, min(1.0, level))

            result = {
                "track_index": track_index,
                "send_index": send_index,
                "level": sends[send_index].value
            }
            return result
        except Exception as e:
            self.log_message("Error setting send level: " + str(e))
            raise

    def _set_return_volume(self, return_index, volume):
        """Set the volume of a return track"""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")

            track = self._song.return_tracks[return_index]
            track.mixer_device.volume.value = max(0.0, min(1.0, volume))

            result = {
                "return_index": return_index,
                "volume": track.mixer_device.volume.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting return volume: " + str(e))
            raise

    def _set_return_pan(self, return_index, pan):
        """Set the panning of a return track"""
        try:
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")

            track = self._song.return_tracks[return_index]
            track.mixer_device.panning.value = max(-1.0, min(1.0, pan))

            result = {
                "return_index": return_index,
                "panning": track.mixer_device.panning.value
            }
            return result
        except Exception as e:
            self.log_message("Error setting return pan: " + str(e))
            raise

    # ==================== VIEW CONTROL ====================

    def _get_current_view(self):
        """Get information about the current view state"""
        try:
            view = self._song.view
            app_view = self.application().view

            result = {
                "selected_track_index": list(self._song.tracks).index(view.selected_track) if view.selected_track in self._song.tracks else -1,
                "selected_track_name": view.selected_track.name if view.selected_track else None,
                "selected_scene_index": list(self._song.scenes).index(view.selected_scene) if view.selected_scene else -1,
                "selected_scene_name": view.selected_scene.name if view.selected_scene else None,
                "is_session_visible": app_view.is_view_visible("Session") if hasattr(app_view, 'is_view_visible') else None,
                "is_arranger_visible": app_view.is_view_visible("Arranger") if hasattr(app_view, 'is_view_visible') else None,
            }
            return result
        except Exception as e:
            self.log_message("Error getting current view: " + str(e))
            raise

    def _focus_view(self, view_name):
        """Focus a specific view (Session, Arranger, Detail, etc.)"""
        try:
            app_view = self.application().view

            if hasattr(app_view, 'focus_view'):
                app_view.focus_view(view_name)

            result = {
                "focused": True,
                "view_name": view_name
            }
            return result
        except Exception as e:
            self.log_message("Error focusing view: " + str(e))
            raise

    def _select_track(self, track_index):
        """Select a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            self._song.view.selected_track = track

            result = {
                "selected": True,
                "track_index": track_index,
                "track_name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error selecting track: " + str(e))
            raise

    def _select_scene(self, scene_index):
        """Select a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")

            scene = self._song.scenes[scene_index]
            self._song.view.selected_scene = scene

            result = {
                "selected": True,
                "scene_index": scene_index,
                "scene_name": scene.name
            }
            return result
        except Exception as e:
            self.log_message("Error selecting scene: " + str(e))
            raise

    def _select_clip(self, track_index, clip_index):
        """Select a clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            # Select the track and scene
            self._song.view.selected_track = track
            if clip_index < len(self._song.scenes):
                self._song.view.selected_scene = self._song.scenes[clip_index]

            # Try to highlight the clip slot
            clip_slot = track.clip_slots[clip_index]
            if hasattr(self._song.view, 'highlighted_clip_slot'):
                self._song.view.highlighted_clip_slot = clip_slot

            result = {
                "selected": True,
                "track_index": track_index,
                "clip_index": clip_index,
                "has_clip": clip_slot.has_clip
            }
            return result
        except Exception as e:
            self.log_message("Error selecting clip: " + str(e))
            raise

    # ==================== RECORDING CONTROL ====================

    def _start_recording(self):
        """Start recording"""
        try:
            self._song.record_mode = True

            result = {
                "recording": self._song.record_mode
            }
            return result
        except Exception as e:
            self.log_message("Error starting recording: " + str(e))
            raise

    def _stop_recording(self):
        """Stop recording"""
        try:
            self._song.record_mode = False

            result = {
                "recording": self._song.record_mode
            }
            return result
        except Exception as e:
            self.log_message("Error stopping recording: " + str(e))
            raise

    def _toggle_session_record(self):
        """Toggle session record mode"""
        try:
            if hasattr(self._song, 'session_record'):
                self._song.session_record = not self._song.session_record
                result = {
                    "session_record": self._song.session_record
                }
            else:
                result = {
                    "error": "Session record not available"
                }
            return result
        except Exception as e:
            self.log_message("Error toggling session record: " + str(e))
            raise

    def _toggle_arrangement_record(self):
        """Toggle arrangement record mode"""
        try:
            self._song.record_mode = not self._song.record_mode

            result = {
                "arrangement_record": self._song.record_mode
            }
            return result
        except Exception as e:
            self.log_message("Error toggling arrangement record: " + str(e))
            raise

    def _set_overdub(self, enabled):
        """Set overdub mode"""
        try:
            if hasattr(self._song, 'overdub'):
                self._song.overdub = enabled
                result = {
                    "overdub": self._song.overdub
                }
            else:
                result = {
                    "error": "Overdub not available"
                }
            return result
        except Exception as e:
            self.log_message("Error setting overdub: " + str(e))
            raise

    def _capture_midi(self):
        """Capture MIDI that was played recently"""
        try:
            if hasattr(self._song, 'capture_midi'):
                self._song.capture_midi()
                result = {
                    "captured": True
                }
            else:
                result = {
                    "captured": False,
                    "error": "Capture MIDI not available"
                }
            return result
        except Exception as e:
            self.log_message("Error capturing MIDI: " + str(e))
            raise

    # ==================== ARRANGEMENT VIEW ====================

    def _get_arrangement_length(self):
        """Get the length of the arrangement"""
        try:
            result = {
                "length": self._song.last_event_time if hasattr(self._song, 'last_event_time') else 0,
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "loop_enabled": self._song.loop if hasattr(self._song, 'loop') else False
            }
            return result
        except Exception as e:
            self.log_message("Error getting arrangement length: " + str(e))
            raise

    def _set_arrangement_loop(self, start, end, enabled):
        """Set the arrangement loop region"""
        try:
            self._song.loop_start = start
            self._song.loop_length = end - start
            if hasattr(self._song, 'loop'):
                self._song.loop = enabled

            result = {
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "loop_enabled": self._song.loop if hasattr(self._song, 'loop') else enabled
            }
            return result
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _jump_to_time(self, time):
        """Jump to a specific time in the arrangement"""
        try:
            self._song.current_song_time = time

            result = {
                "current_time": self._song.current_song_time
            }
            return result
        except Exception as e:
            self.log_message("Error jumping to time: " + str(e))
            raise

    def _get_locators(self):
        """Get all locators/cue points"""
        try:
            locators = []
            if hasattr(self._song, 'cue_points'):
                for i, cue in enumerate(self._song.cue_points):
                    locators.append({
                        "index": i,
                        "name": cue.name,
                        "time": cue.time
                    })

            result = {
                "locator_count": len(locators),
                "locators": locators
            }
            return result
        except Exception as e:
            self.log_message("Error getting locators: " + str(e))
            raise

    def _create_locator(self, time, name):
        """Create a new locator/cue point"""
        try:
            if hasattr(self._song, 'set_or_delete_cue'):
                self._song.set_or_delete_cue()
                result = {
                    "created": True,
                    "time": time,
                    "name": name
                }
            else:
                result = {
                    "created": False,
                    "error": "Locator creation not available"
                }
            return result
        except Exception as e:
            self.log_message("Error creating locator: " + str(e))
            raise

    def _delete_locator(self, locator_index):
        """Delete a locator"""
        try:
            if hasattr(self._song, 'cue_points') and locator_index < len(self._song.cue_points):
                cue = self._song.cue_points[locator_index]
                cue_name = cue.name
                cue.time = -1  # Setting time to -1 deletes the cue point
                result = {
                    "deleted": True,
                    "locator_index": locator_index,
                    "name": cue_name
                }
            else:
                result = {
                    "deleted": False,
                    "error": "Locator not found"
                }
            return result
        except Exception as e:
            self.log_message("Error deleting locator: " + str(e))
            raise

    # ==================== INPUT/OUTPUT ROUTING ====================

    def _get_track_input_routing(self, track_index):
        """Get the input routing of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            result = {
                "track_index": track_index,
                "input_routing_type": str(track.input_routing_type.display_name) if hasattr(track.input_routing_type, 'display_name') else str(track.input_routing_type),
                "input_routing_channel": str(track.input_routing_channel.display_name) if hasattr(track.input_routing_channel, 'display_name') else str(track.input_routing_channel)
            }
            return result
        except Exception as e:
            self.log_message("Error getting track input routing: " + str(e))
            raise

    def _get_track_output_routing(self, track_index):
        """Get the output routing of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            result = {
                "track_index": track_index,
                "output_routing_type": str(track.output_routing_type.display_name) if hasattr(track.output_routing_type, 'display_name') else str(track.output_routing_type),
                "output_routing_channel": str(track.output_routing_channel.display_name) if hasattr(track.output_routing_channel, 'display_name') else str(track.output_routing_channel)
            }
            return result
        except Exception as e:
            self.log_message("Error getting track output routing: " + str(e))
            raise

    def _get_available_inputs(self, track_index):
        """Get available input routing options for a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            inputs = []

            if hasattr(track, 'available_input_routing_types'):
                for rt in track.available_input_routing_types:
                    inputs.append(str(rt.display_name) if hasattr(rt, 'display_name') else str(rt))

            result = {
                "track_index": track_index,
                "available_inputs": inputs
            }
            return result
        except Exception as e:
            self.log_message("Error getting available inputs: " + str(e))
            raise

    def _get_available_outputs(self, track_index):
        """Get available output routing options for a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]
            outputs = []

            if hasattr(track, 'available_output_routing_types'):
                for rt in track.available_output_routing_types:
                    outputs.append(str(rt.display_name) if hasattr(rt, 'display_name') else str(rt))

            result = {
                "track_index": track_index,
                "available_outputs": outputs
            }
            return result
        except Exception as e:
            self.log_message("Error getting available outputs: " + str(e))
            raise

    def _set_track_input_routing(self, track_index, routing_type, routing_channel):
        """Set the input routing of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            # Find and set the routing type
            if hasattr(track, 'available_input_routing_types'):
                for rt in track.available_input_routing_types:
                    rt_name = str(rt.display_name) if hasattr(rt, 'display_name') else str(rt)
                    if rt_name.lower() == routing_type.lower():
                        track.input_routing_type = rt
                        break

            result = {
                "track_index": track_index,
                "input_routing_type": str(track.input_routing_type.display_name) if hasattr(track.input_routing_type, 'display_name') else str(track.input_routing_type)
            }
            return result
        except Exception as e:
            self.log_message("Error setting track input routing: " + str(e))
            raise

    def _set_track_output_routing(self, track_index, routing_type, routing_channel):
        """Set the output routing of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            # Find and set the routing type
            if hasattr(track, 'available_output_routing_types'):
                for rt in track.available_output_routing_types:
                    rt_name = str(rt.display_name) if hasattr(rt, 'display_name') else str(rt)
                    if rt_name.lower() == routing_type.lower():
                        track.output_routing_type = rt
                        break

            result = {
                "track_index": track_index,
                "output_routing_type": str(track.output_routing_type.display_name) if hasattr(track.output_routing_type, 'display_name') else str(track.output_routing_type)
            }
            return result
        except Exception as e:
            self.log_message("Error setting track output routing: " + str(e))
            raise

    # ==================== PERFORMANCE & SESSION ====================

    def _get_cpu_load(self):
        """Get the current CPU load"""
        try:
            app = self.application()
            result = {
                "cpu_load": app.get_cpu_load() if hasattr(app, 'get_cpu_load') else None
            }
            return result
        except Exception as e:
            self.log_message("Error getting CPU load: " + str(e))
            raise

    def _get_session_path(self):
        """Get the path of the current session"""
        try:
            app = self.application()
            doc = app.get_document() if hasattr(app, 'get_document') else None

            result = {
                "path": doc.file_path if doc and hasattr(doc, 'file_path') else None,
                "name": self._song.name if hasattr(self._song, 'name') else None
            }
            return result
        except Exception as e:
            self.log_message("Error getting session path: " + str(e))
            raise

    def _is_session_modified(self):
        """Check if the session has unsaved changes"""
        try:
            app = self.application()
            doc = app.get_document() if hasattr(app, 'get_document') else None

            result = {
                "modified": doc.is_modified if doc and hasattr(doc, 'is_modified') else None
            }
            return result
        except Exception as e:
            self.log_message("Error checking session modified: " + str(e))
            raise

    def _get_metronome_state(self):
        """Get the metronome state"""
        try:
            result = {
                "enabled": self._song.metronome if hasattr(self._song, 'metronome') else None
            }
            return result
        except Exception as e:
            self.log_message("Error getting metronome state: " + str(e))
            raise

    def _set_metronome(self, enabled):
        """Set the metronome on/off"""
        try:
            if hasattr(self._song, 'metronome'):
                self._song.metronome = enabled

            result = {
                "enabled": self._song.metronome if hasattr(self._song, 'metronome') else enabled
            }
            return result
        except Exception as e:
            self.log_message("Error setting metronome: " + str(e))
            raise

    # ==================== AI MUSIC HELPERS ====================

    def _get_scale_notes(self, root, scale_type):
        """Get notes in a scale"""
        try:
            # Scale intervals (semitones from root)
            scales = {
                "major": [0, 2, 4, 5, 7, 9, 11],
                "minor": [0, 2, 3, 5, 7, 8, 10],
                "dorian": [0, 2, 3, 5, 7, 9, 10],
                "phrygian": [0, 1, 3, 5, 7, 8, 10],
                "lydian": [0, 2, 4, 6, 7, 9, 11],
                "mixolydian": [0, 2, 4, 5, 7, 9, 10],
                "locrian": [0, 1, 3, 5, 6, 8, 10],
                "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],
                "melodic_minor": [0, 2, 3, 5, 7, 9, 11],
                "pentatonic_major": [0, 2, 4, 7, 9],
                "pentatonic_minor": [0, 3, 5, 7, 10],
                "blues": [0, 3, 5, 6, 7, 10],
                "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
            }

            scale = scales.get(scale_type.lower(), scales["major"])
            notes = [(root + interval) % 12 for interval in scale]
            midi_notes = [root + interval for interval in scale]

            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

            result = {
                "root": root,
                "root_name": note_names[root % 12],
                "scale_type": scale_type,
                "intervals": scale,
                "notes": notes,
                "note_names": [note_names[n] for n in notes],
                "midi_notes_octave": midi_notes
            }
            return result
        except Exception as e:
            self.log_message("Error getting scale notes: " + str(e))
            raise

    def _quantize_clip_notes(self, track_index, clip_index, grid):
        """Quantize notes in a clip to a grid"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            # Get notes
            clip.select_all_notes()
            notes_data = clip.get_selected_notes()
            clip.deselect_all_notes()

            # Quantize notes
            quantized_notes = []
            for note in notes_data:
                pitch, start, duration, velocity, mute = note
                quantized_start = round(start / grid) * grid
                quantized_notes.append((pitch, quantized_start, duration, velocity, mute))

            # Set quantized notes
            clip.remove_notes(0, 0, clip.length, 128)
            clip.set_notes(tuple(quantized_notes))

            result = {
                "quantized": True,
                "note_count": len(quantized_notes),
                "grid": grid
            }
            return result
        except Exception as e:
            self.log_message("Error quantizing clip notes: " + str(e))
            raise

    def _humanize_clip_timing(self, track_index, clip_index, amount):
        """Add random timing variation to notes"""
        try:
            import random

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            # Get notes
            clip.select_all_notes()
            notes_data = clip.get_selected_notes()
            clip.deselect_all_notes()

            # Humanize timing
            humanized_notes = []
            for note in notes_data:
                pitch, start, duration, velocity, mute = note
                # Add random offset (amount is in beats, e.g., 0.1 = 10% of a beat)
                offset = (random.random() - 0.5) * 2 * amount
                new_start = max(0, start + offset)
                humanized_notes.append((pitch, new_start, duration, velocity, mute))

            # Set humanized notes
            clip.remove_notes(0, 0, clip.length, 128)
            clip.set_notes(tuple(humanized_notes))

            result = {
                "humanized": True,
                "note_count": len(humanized_notes),
                "amount": amount
            }
            return result
        except Exception as e:
            self.log_message("Error humanizing clip timing: " + str(e))
            raise

    def _humanize_clip_velocity(self, track_index, clip_index, amount):
        """Add random velocity variation to notes"""
        try:
            import random

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if not clip_slot.has_clip:
                raise Exception("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_midi_clip:
                raise Exception("Clip is not a MIDI clip")

            # Get notes
            clip.select_all_notes()
            notes_data = clip.get_selected_notes()
            clip.deselect_all_notes()

            # Humanize velocity
            humanized_notes = []
            for note in notes_data:
                pitch, start, duration, velocity, mute = note
                # Add random velocity variation (amount is 0-1, e.g., 0.1 = +/-10% variation)
                variation = int((random.random() - 0.5) * 2 * amount * 127)
                new_velocity = max(1, min(127, velocity + variation))
                humanized_notes.append((pitch, start, duration, new_velocity, mute))

            # Set humanized notes
            clip.remove_notes(0, 0, clip.length, 128)
            clip.set_notes(tuple(humanized_notes))

            result = {
                "humanized": True,
                "note_count": len(humanized_notes),
                "amount": amount
            }
            return result
        except Exception as e:
            self.log_message("Error humanizing clip velocity: " + str(e))
            raise

    def _generate_drum_pattern(self, track_index, clip_index, style, length):
        """Generate a drum pattern"""
        try:
            import random

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            # Create clip if it doesn't exist
            if not clip_slot.has_clip:
                clip_slot.create_clip(length)

            clip = clip_slot.clip

            # Clear existing notes
            clip.remove_notes(0, 0, clip.length, 128)

            # Drum mappings (General MIDI)
            KICK = 36
            SNARE = 38
            CLOSED_HH = 42
            OPEN_HH = 46
            CLAP = 39

            notes = []
            beats = int(length)

            if style == "basic":
                # Basic 4/4 pattern
                for beat in range(beats):
                    # Kick on 1 and 3
                    if beat % 2 == 0:
                        notes.append((KICK, float(beat), 0.25, 100, False))
                    # Snare on 2 and 4
                    if beat % 2 == 1:
                        notes.append((SNARE, float(beat), 0.25, 100, False))
                    # Hi-hat on every 8th
                    for eighth in range(2):
                        notes.append((CLOSED_HH, beat + eighth * 0.5, 0.25, 80, False))

            elif style == "house":
                # House pattern - 4 on the floor
                for beat in range(beats):
                    notes.append((KICK, float(beat), 0.25, 110, False))
                    if beat % 2 == 1:
                        notes.append((CLAP, float(beat), 0.25, 100, False))
                    # Offbeat hi-hats
                    notes.append((OPEN_HH, beat + 0.5, 0.25, 90, False))

            elif style == "hiphop":
                # Hip-hop pattern
                for beat in range(beats):
                    # Kick pattern
                    if beat % 4 == 0:
                        notes.append((KICK, float(beat), 0.25, 110, False))
                    if beat % 4 == 2:
                        notes.append((KICK, beat + 0.75, 0.25, 90, False))
                    # Snare on 2 and 4
                    if beat % 2 == 1:
                        notes.append((SNARE, float(beat), 0.25, 100, False))
                    # Hi-hats
                    for eighth in range(2):
                        vel = 80 if eighth == 0 else 60
                        notes.append((CLOSED_HH, beat + eighth * 0.5, 0.25, vel, False))

            elif style == "dnb":
                # Drum and bass pattern
                for beat in range(beats):
                    # Two-step kick pattern
                    if beat % 4 == 0:
                        notes.append((KICK, float(beat), 0.25, 110, False))
                    if beat % 4 == 2:
                        notes.append((KICK, beat + 0.5, 0.25, 100, False))
                    # Snare on 2 and 4
                    if beat % 2 == 1:
                        notes.append((SNARE, float(beat), 0.25, 110, False))
                    # Fast hi-hats
                    for sixteenth in range(4):
                        vel = 70 + random.randint(-10, 10)
                        notes.append((CLOSED_HH, beat + sixteenth * 0.25, 0.125, vel, False))

            else:  # Random/experimental
                for beat in range(beats):
                    if random.random() > 0.3:
                        notes.append((KICK, beat + random.choice([0, 0.5]), 0.25, random.randint(80, 110), False))
                    if random.random() > 0.5:
                        notes.append((SNARE, beat + random.choice([0, 0.25, 0.5]), 0.25, random.randint(80, 100), False))
                    if random.random() > 0.2:
                        notes.append((CLOSED_HH, beat + random.random() * 0.5, 0.25, random.randint(60, 90), False))

            # Set the notes
            clip.set_notes(tuple(notes))

            result = {
                "generated": True,
                "style": style,
                "length": length,
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error generating drum pattern: " + str(e))
            raise

    def _generate_bassline(self, track_index, clip_index, root, scale_type, length):
        """Generate a bassline pattern"""
        try:
            import random

            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            # Create clip if it doesn't exist
            if not clip_slot.has_clip:
                clip_slot.create_clip(length)

            clip = clip_slot.clip

            # Clear existing notes
            clip.remove_notes(0, 0, clip.length, 128)

            # Get scale notes
            scales = {
                "major": [0, 2, 4, 5, 7, 9, 11],
                "minor": [0, 2, 3, 5, 7, 8, 10],
                "dorian": [0, 2, 3, 5, 7, 9, 10],
                "phrygian": [0, 1, 3, 5, 7, 8, 10],
                "pentatonic_minor": [0, 3, 5, 7, 10],
                "blues": [0, 3, 5, 6, 7, 10]
            }
            scale = scales.get(scale_type.lower(), scales["minor"])

            notes = []
            beats = int(length)
            current_note = root

            for beat in range(beats):
                # Root note on beat 1
                if beat % 4 == 0:
                    notes.append((root, float(beat), 0.5, 100, False))
                else:
                    # Choose from scale
                    interval = random.choice(scale)
                    note = root + interval
                    # Vary octave occasionally
                    if random.random() > 0.7:
                        note += 12
                    duration = random.choice([0.25, 0.5, 0.75])
                    velocity = random.randint(80, 110)
                    notes.append((note, float(beat), duration, velocity, False))

                # Add some 8th note movement
                if random.random() > 0.5:
                    interval = random.choice(scale)
                    note = root + interval
                    notes.append((note, beat + 0.5, 0.25, random.randint(70, 90), False))

            # Set the notes
            clip.set_notes(tuple(notes))

            result = {
                "generated": True,
                "root": root,
                "scale_type": scale_type,
                "length": length,
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error generating bassline: " + str(e))
            raise

    # =========================================================================
    # Audio Clip Editing
    # =========================================================================

    def _set_clip_gain(self, track_index, clip_index, gain):
        """Set the gain of an audio clip in dB"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            # Check if it's an audio clip
            if not clip.is_audio_clip:
                raise ValueError("Clip is not an audio clip")

            # Gain is in dB, convert to Ableton's linear gain
            # Ableton uses a range where 0dB = 1.0
            import math
            linear_gain = math.pow(10, gain / 20.0)
            clip.gain = max(0.0, min(4.0, linear_gain))  # Clamp to reasonable range

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "gain_db": gain,
                "gain_linear": clip.gain
            }
        except Exception as e:
            self.log_message("Error setting clip gain: " + str(e))
            raise

    def _set_clip_pitch(self, track_index, clip_index, pitch):
        """Set the pitch shift of an audio clip in semitones"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_audio_clip:
                raise ValueError("Clip is not an audio clip")

            # Pitch coarse is in semitones (-48 to +48)
            pitch = max(-48, min(48, int(pitch)))
            clip.pitch_coarse = pitch

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "pitch_semitones": clip.pitch_coarse
            }
        except Exception as e:
            self.log_message("Error setting clip pitch: " + str(e))
            raise

    def _set_clip_warp_mode(self, track_index, clip_index, warp_mode):
        """Set the warp mode of an audio clip"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_audio_clip:
                raise ValueError("Clip is not an audio clip")

            # Warp modes: beats, tones, texture, repitch, complex, complex_pro
            warp_modes = {
                "beats": 0,
                "tones": 1,
                "texture": 2,
                "repitch": 3,
                "complex": 4,
                "complex_pro": 5
            }

            mode_value = warp_modes.get(warp_mode.lower(), 0)
            clip.warp_mode = mode_value

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "warp_mode": warp_mode,
                "warp_mode_value": mode_value
            }
        except Exception as e:
            self.log_message("Error setting warp mode: " + str(e))
            raise

    def _get_clip_warp_info(self, track_index, clip_index):
        """Get warp info for an audio clip"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            if not clip.is_audio_clip:
                raise ValueError("Clip is not an audio clip")

            warp_mode_names = ["beats", "tones", "texture", "repitch", "complex", "complex_pro"]

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "warping": clip.warping,
                "warp_mode": warp_mode_names[clip.warp_mode] if clip.warp_mode < len(warp_mode_names) else "unknown",
                "warp_mode_value": clip.warp_mode,
                "gain": clip.gain,
                "pitch_coarse": clip.pitch_coarse,
                "pitch_fine": clip.pitch_fine if hasattr(clip, 'pitch_fine') else 0
            }
        except Exception as e:
            self.log_message("Error getting warp info: " + str(e))
            raise

    # =========================================================================
    # Clip Automation
    # =========================================================================

    def _get_clip_automation(self, track_index, clip_index, parameter_name, device_index=None, samples=33):
        """Read a clip's automation curve.

        Live's API exposes no breakpoint list, so the previous version just
        returned has_automation=True and nothing else - the curve was unverifiable.
        envelope.value_at_time() IS available, so sample the curve instead and
        return the real shape.
        """
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip
            track = self._song.tracks[track_index]
            param, owner_name = self._find_track_param(track, parameter_name, device_index)

            envelope = clip.automation_envelope(param) if hasattr(clip, 'automation_envelope') else None
            base = {
                "track_index": track_index, "clip_index": clip_index,
                "parameter_name": param.name, "device_name": owner_name,
                "parameter_min": param.min, "parameter_max": param.max,
                "parameter_value": param.value, "clip_length": clip.length,
            }
            if not envelope:
                base.update({"has_automation": False, "envelope_data": []})
                return base

            n = max(2, min(int(samples), 257))
            pts, length = [], clip.length
            for i in range(n):
                t = length * i / float(n - 1)
                try:
                    v = envelope.value_at_time(t)
                except Exception:
                    v = None
                pts.append({"time": round(t, 4), "value": v})

            vals = [p["value"] for p in pts if p["value"] is not None]
            base.update({
                "has_automation": True,
                "sampled_points": n,
                "envelope_data": pts,
                "value_min": min(vals) if vals else None,
                "value_max": max(vals) if vals else None,
                "is_flat": (max(vals) - min(vals) < 1e-6) if vals else None,
            })
            return base
        except Exception as e:
            self.log_message("Error getting clip automation: " + str(e))
            raise

    def _set_clip_automation(self, track_index, clip_index, parameter_name, envelope_data, device_index=None):
        """Set automation envelope for a clip parameter"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip
            track = self._song.tracks[track_index]

            param, owner_name = self._find_track_param(track, parameter_name, device_index)

            # Create/get envelope
            if hasattr(clip, 'create_automation_envelope'):
                envelope = clip.create_automation_envelope(param)
            else:
                return {"error": "Automation envelopes not supported in this version"}

            # Clear existing and add new points
            if hasattr(envelope, 'clear'):
                envelope.clear()

            # Add breakpoints from envelope_data
            # envelope_data format: [{"time": float, "value": float}, ...]
            for point in envelope_data:
                time = point.get("time", 0)
                value = point.get("value", param.value)
                if hasattr(envelope, 'insert_value'):
                    envelope.insert_value(time, value)

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": parameter_name,
                "points_added": len(envelope_data)
            }
        except Exception as e:
            self.log_message("Error setting clip automation: " + str(e))
            raise

    def _create_group_track(self, track_indices, name):
        """Create a group track containing the specified tracks"""
        try:
            if not track_indices:
                raise ValueError("No tracks specified for grouping")

            # Validate all track indices
            for idx in track_indices:
                if idx < 0 or idx >= len(self._song.tracks):
                    raise IndexError("Track index {0} out of range".format(idx))

            # Sort indices in descending order for proper grouping
            sorted_indices = sorted(track_indices, reverse=True)

            # Select the tracks
            for idx in sorted_indices:
                self._song.tracks[idx].is_grouped = True

            # Create group - this may require using Live's grouping functionality
            # In Ableton's API, tracks can be grouped by setting is_part_of_selection
            # and using the song's create_group_track method if available

            if hasattr(self._song, 'create_group_track'):
                # Select the tracks first
                self._song.view.selected_track = self._song.tracks[sorted_indices[0]]
                group_track = self._song.create_group_track(sorted_indices[0])
                if name:
                    group_track.name = name

                return {
                    "created": True,
                    "group_track_index": list(self._song.tracks).index(group_track),
                    "grouped_tracks": track_indices,
                    "name": name
                }
            else:
                return {
                    "error": "Group track creation not supported in this Ableton version",
                    "note": "Try selecting tracks manually and using Cmd+G"
                }
        except Exception as e:
            self.log_message("Error creating group track: " + str(e))
            raise

    def _ungroup_tracks(self, group_track_index):
        """Ungroup a group track"""
        try:
            track = self._validate_track_index(group_track_index)

            if not track.is_foldable:
                raise ValueError("Track is not a group track")

            if hasattr(track, 'ungroup'):
                track.ungroup()
                return {"ungrouped": True, "track_index": group_track_index}
            else:
                return {"error": "Ungrouping not supported in this Ableton version"}
        except Exception as e:
            self.log_message("Error ungrouping tracks: " + str(e))
            raise

    def _fold_track(self, track_index, fold):
        """Fold or unfold a group track"""
        try:
            track = self._validate_track_index(track_index)

            if not track.is_foldable:
                raise ValueError("Track is not foldable (not a group track)")

            track.fold_state = fold

            return {
                "track_index": track_index,
                "folded": track.fold_state
            }
        except Exception as e:
            self.log_message("Error folding track: " + str(e))
            raise

    # =========================================================================
    # Track Monitoring
    # =========================================================================

    def _set_track_monitoring(self, track_index, monitoring):
        """Set track monitoring mode (in, auto, off)"""
        try:
            track = self._validate_track_index(track_index)

            if not track.can_be_armed:
                raise ValueError("Track cannot be monitored (not an audio/MIDI track)")

            # Monitoring states: 0=In, 1=Auto, 2=Off
            monitoring_map = {
                "in": 0,
                "auto": 1,
                "off": 2
            }

            mode = monitoring_map.get(monitoring.lower(), 1)
            track.current_monitoring_state = mode

            return {
                "track_index": track_index,
                "monitoring": monitoring,
                "monitoring_value": mode
            }
        except Exception as e:
            self.log_message("Error setting track monitoring: " + str(e))
            raise

    def _get_track_monitoring(self, track_index):
        """Get track monitoring mode"""
        try:
            track = self._validate_track_index(track_index)

            if not track.can_be_armed:
                return {"track_index": track_index, "monitoring": "n/a", "can_monitor": False}

            monitoring_names = ["in", "auto", "off"]
            state = track.current_monitoring_state

            return {
                "track_index": track_index,
                "monitoring": monitoring_names[state] if state < len(monitoring_names) else "unknown",
                "monitoring_value": state,
                "can_monitor": True
            }
        except Exception as e:
            self.log_message("Error getting track monitoring: " + str(e))
            raise

    # =========================================================================
    # Device Presets and Rack Chains
    # =========================================================================

    def _get_device_by_name(self, track_index, device_name):
        """Find a device by name and return its info"""
        try:
            track = self._validate_track_index(track_index)

            for i, device in enumerate(track.devices):
                if device.name.lower() == device_name.lower():
                    params = []
                    for j, param in enumerate(device.parameters):
                        params.append({
                            "index": j,
                            "name": param.name,
                            "value": param.value,
                            "min": param.min,
                            "max": param.max
                        })

                    return {
                        "found": True,
                        "device_index": i,
                        "name": device.name,
                        "class_name": device.class_name,
                        "is_active": device.is_active,
                        "parameters": params
                    }

            return {
                "found": False,
                "device_name": device_name,
                "available_devices": [d.name for d in track.devices]
            }
        except Exception as e:
            self.log_message("Error getting device by name: " + str(e))
            raise

    def _load_device_preset(self, track_index, device_index, preset_uri):
        """Load a preset onto a device"""
        try:
            track = self._validate_track_index(track_index)
            device = self._validate_device_index(track, device_index)

            app = self.application()
            browser = app.browser

            # Find preset in browser
            item = self._find_browser_item_by_uri(browser, preset_uri)

            if not item:
                return {"error": "Preset not found: " + preset_uri}

            if not item.is_loadable:
                return {"error": "Item is not loadable"}

            # Select the device first, then load preset
            self._song.view.selected_track = track
            # Note: Loading presets directly onto devices may require
            # using the browser's hot-swap functionality

            if hasattr(browser, 'hotswap_target'):
                browser.hotswap_target = device
                browser.load_item(item)
                return {
                    "loaded": True,
                    "preset_name": item.name,
                    "device_name": device.name
                }
            else:
                return {"error": "Preset loading not fully supported"}
        except Exception as e:
            self.log_message("Error loading device preset: " + str(e))
            raise

    def _get_rack_chains(self, track_index, device_index):
        """Get chains from an instrument/effect rack"""
        try:
            track = self._validate_track_index(track_index)
            device = self._validate_device_index(track, device_index)

            if not device.can_have_chains:
                return {"error": "Device is not a rack", "device_name": device.name}

            chains = []
            for i, chain in enumerate(device.chains):
                chains.append({
                    "index": i,
                    "name": chain.name,
                    "mute": chain.mute,
                    "solo": chain.solo,
                    "device_count": len(chain.devices)
                })

            return {
                "track_index": track_index,
                "device_index": device_index,
                "device_name": device.name,
                "chain_count": len(chains),
                "chains": chains
            }
        except Exception as e:
            self.log_message("Error getting rack chains: " + str(e))
            raise

    def _select_rack_chain(self, track_index, device_index, chain_index):
        """Select a chain in a rack"""
        try:
            track = self._validate_track_index(track_index)
            device = self._validate_device_index(track, device_index)

            if not device.can_have_chains:
                raise ValueError("Device is not a rack")

            if chain_index < 0 or chain_index >= len(device.chains):
                raise IndexError("Chain index out of range")

            # Select the chain
            if hasattr(device, 'view') and hasattr(device.view, 'selected_chain_index'):
                device.view.selected_chain_index = chain_index

            return {
                "track_index": track_index,
                "device_index": device_index,
                "chain_index": chain_index,
                "chain_name": device.chains[chain_index].name
            }
        except Exception as e:
            self.log_message("Error selecting rack chain: " + str(e))
            raise

    # =========================================================================
    # Groove Pool
    # =========================================================================

    def _get_groove_pool(self):
        """Get available grooves from the groove pool"""
        try:
            if not hasattr(self._song, 'groove_pool') or not self._song.groove_pool:
                return {"error": "Groove pool not available", "grooves": []}

            grooves = []
            for i, groove in enumerate(self._song.groove_pool.grooves):
                grooves.append({
                    "index": i,
                    "name": groove.name if hasattr(groove, 'name') else "Groove " + str(i),
                    "amount": groove.amount if hasattr(groove, 'amount') else 1.0
                })

            return {
                "groove_count": len(grooves),
                "grooves": grooves
            }
        except Exception as e:
            self.log_message("Error getting groove pool: " + str(e))
            raise

    def _apply_groove(self, track_index, clip_index, groove_index):
        """Apply a groove to a clip"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            if not hasattr(self._song, 'groove_pool') or not self._song.groove_pool:
                return {"error": "Groove pool not available"}

            grooves = list(self._song.groove_pool.grooves)
            if groove_index < 0 or groove_index >= len(grooves):
                raise IndexError("Groove index out of range")

            groove = grooves[groove_index]

            # Apply groove to clip
            if hasattr(clip, 'groove'):
                clip.groove = groove
                return {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "groove_applied": True,
                    "groove_name": groove.name if hasattr(groove, 'name') else "Groove " + str(groove_index)
                }
            else:
                return {"error": "Groove assignment not supported"}
        except Exception as e:
            self.log_message("Error applying groove: " + str(e))
            raise

    def _commit_groove(self, track_index, clip_index):
        """Commit groove quantization to clip notes"""
        try:
            clip_slot = self._validate_clip_slot(track_index, clip_index)
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot")

            clip = clip_slot.clip

            # Commit groove (make it permanent)
            if hasattr(clip, 'quantize'):
                # This will apply the groove permanently
                clip.quantize(0.125, 1.0)  # Quantize to 32nd notes with full strength

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "committed": True
            }
        except Exception as e:
            self.log_message("Error committing groove: " + str(e))
            raise

    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri):
        """Load a browser item onto a track by its URI"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            
            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)
            
            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))
            
            # Select the track
            self._song.view.selected_track = track
            
            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects
                ]

                # VST/AU plug-ins, Max for Live, the user library and packs are
                # also loadable. The old list stopped at the five built-in
                # categories, which is why "the API can't load plug-ins" - it
                # just never searched the plugins root.
                for extra in ("plugins", "max_for_live", "user_library", "packs"):
                    if hasattr(browser_or_item, extra):
                        categories.append(getattr(browser_or_item, extra))

                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except (AttributeError, TypeError) as e:
            self.log_message("Error getting device type: " + str(e))
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result

        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise

    # ============================================================================
    # Missing GET Methods (for 100% coverage)
    # ============================================================================

    def _get_track_color(self, track_index):
        """Get the color index of a track"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            return {"color_index": track.color_index}
        except Exception as e:
            self.log_message("Error getting track color: " + str(e))
            return {"error": str(e)}

    def _get_clip_color(self, track_index, clip_index):
        """Get the color index of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            return {"color_index": clip.color_index}
        except Exception as e:
            self.log_message("Error getting clip color: " + str(e))
            return {"error": str(e)}

    def _get_scene_color(self, scene_index):
        """Get the color index of a scene"""
        try:
            scenes = list(self._song.scenes)
            if scene_index >= len(scenes):
                return {"error": "Scene index out of range"}
            scene = scenes[scene_index]
            return {"color_index": scene.color_index}
        except Exception as e:
            self.log_message("Error getting scene color: " + str(e))
            return {"error": str(e)}

    def _get_clip_gain(self, track_index, clip_index):
        """Get the gain of an audio clip in dB"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "Gain only applies to audio clips"}
            # gain is in dB, typically -inf to +35.5dB
            return {
                "gain_db": clip.gain,
                "gain_display": clip.gain_display_string if hasattr(clip, 'gain_display_string') else str(clip.gain) + " dB"
            }
        except Exception as e:
            self.log_message("Error getting clip gain: " + str(e))
            return {"error": str(e)}

    def _get_clip_pitch(self, track_index, clip_index):
        """Get the pitch shift of an audio clip in semitones"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "Pitch shift only applies to audio clips"}
            # pitch_coarse is in semitones (-48 to +48)
            # pitch_fine is in cents (-50 to +50)
            return {
                "pitch_coarse": clip.pitch_coarse,
                "pitch_fine": clip.pitch_fine,
                "pitch_semitones": clip.pitch_coarse + (clip.pitch_fine / 100.0)
            }
        except Exception as e:
            self.log_message("Error getting clip pitch: " + str(e))
            return {"error": str(e)}

    def _get_clip_loop(self, track_index, clip_index):
        """Get the loop settings of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            return {
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "looping": clip.looping,
                "loop_length": clip.loop_end - clip.loop_start
            }
        except Exception as e:
            self.log_message("Error getting clip loop: " + str(e))
            return {"error": str(e)}

    def _get_send_level(self, track_index, send_index):
        """Get the send level from a track to a return track"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            sends = list(track.mixer_device.sends)
            if send_index >= len(sends):
                return {"error": "Send index out of range (max: {0})".format(len(sends) - 1)}
            send = sends[send_index]
            return {
                "level": send.value,
                "min": send.min,
                "max": send.max,
                "name": send.name
            }
        except Exception as e:
            self.log_message("Error getting send level: " + str(e))
            return {"error": str(e)}

    def _get_warp_markers(self, track_index, clip_index):
        """Get all warp markers from an audio clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "Warp markers only apply to audio clips"}
            if not clip.warping:
                return {"error": "Warping is disabled for this clip", "warping": False}

            # Get warp markers
            markers = []
            if hasattr(clip, 'warp_markers'):
                for i, marker in enumerate(clip.warp_markers):
                    markers.append({
                        "index": i,
                        "beat_time": marker.beat_time,
                        "sample_time": marker.sample_time
                    })

            return {
                "warping": clip.warping,
                "warp_mode": clip.warp_mode if hasattr(clip, 'warp_mode') else None,
                "warp_markers": markers,
                "count": len(markers)
            }
        except Exception as e:
            self.log_message("Error getting warp markers: " + str(e))
            return {"error": str(e)}

    def _add_warp_marker(self, track_index, clip_index, beat_time, sample_time=None):
        """Add a warp marker to an audio clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "Warp markers only apply to audio clips"}
            if not clip.warping:
                return {"error": "Warping is disabled for this clip"}

            # Add warp marker
            if sample_time is not None:
                clip.insert_warp_marker(beat_time, sample_time)
            else:
                # If no sample_time provided, use the current time at this beat position
                clip.insert_warp_marker(beat_time)

            return {"success": True, "beat_time": beat_time, "sample_time": sample_time}
        except Exception as e:
            self.log_message("Error adding warp marker: " + str(e))
            return {"error": str(e)}

    def _delete_warp_marker(self, track_index, clip_index, beat_time):
        """Delete a warp marker from an audio clip by beat time"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "Warp markers only apply to audio clips"}
            if not clip.warping:
                return {"error": "Warping is disabled for this clip"}

            # Find and delete the warp marker at the given beat time
            if hasattr(clip, 'warp_markers'):
                for marker in clip.warp_markers:
                    if abs(marker.beat_time - beat_time) < 0.001:  # Small tolerance
                        clip.remove_warp_marker(beat_time)
                        return {"success": True, "beat_time": beat_time}

            return {"error": "No warp marker found at beat time {0}".format(beat_time)}
        except Exception as e:
            self.log_message("Error deleting warp marker: " + str(e))
            return {"error": str(e)}

    def _clear_clip_automation(self, track_index, clip_index, parameter_name, device_index=None):
        """Clear automation envelope for a parameter in a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            # Find the parameter
            # First check track mixer parameters
            mixer = track.mixer_device
            param = None
            if parameter_name.lower() == "volume":
                param = mixer.volume
            elif parameter_name.lower() == "pan" or parameter_name.lower() == "panning":
                param = mixer.panning

            if param is None:
                return {"error": "Parameter '{0}' not found".format(parameter_name)}

            # Clear the automation
            clip.clear_envelope(param)

            return {"success": True, "parameter": parameter_name}
        except Exception as e:
            self.log_message("Error clearing clip automation: " + str(e))
            return {"error": str(e)}

    # ============================================================================
    # TIER 1: Critical Missing LOM Features for 100% Coverage
    # ============================================================================

    def _get_clip_launch_mode(self, track_index, clip_index):
        """Get the launch mode of a clip (retrigger, gate, toggle, repeat)"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            # Launch mode: 0=trigger, 1=gate, 2=toggle, 3=repeat
            mode_names = ["trigger", "gate", "toggle", "repeat"]
            mode = clip.launch_mode if hasattr(clip, 'launch_mode') else 0
            return {
                "launch_mode": mode,
                "launch_mode_name": mode_names[mode] if mode < len(mode_names) else "unknown"
            }
        except Exception as e:
            self.log_message("Error getting clip launch mode: " + str(e))
            return {"error": str(e)}

    def _set_clip_launch_mode(self, track_index, clip_index, mode):
        """Set the launch mode of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            # Convert mode name to number if needed
            mode_names = {"trigger": 0, "gate": 1, "toggle": 2, "repeat": 3}
            if isinstance(mode, str):
                mode = mode_names.get(mode.lower(), 0)

            clip.launch_mode = mode
            return {"success": True, "launch_mode": mode}
        except Exception as e:
            self.log_message("Error setting clip launch mode: " + str(e))
            return {"error": str(e)}

    def _get_clip_launch_quantization(self, track_index, clip_index):
        """Get the launch quantization of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            quant = clip.launch_quantization if hasattr(clip, 'launch_quantization') else 0
            return {"launch_quantization": quant}
        except Exception as e:
            self.log_message("Error getting clip launch quantization: " + str(e))
            return {"error": str(e)}

    def _set_clip_launch_quantization(self, track_index, clip_index, quantization):
        """Set the launch quantization of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            clip.launch_quantization = quantization
            return {"success": True, "launch_quantization": quantization}
        except Exception as e:
            self.log_message("Error setting clip launch quantization: " + str(e))
            return {"error": str(e)}

    def _get_clip_follow_action(self, track_index, clip_index):
        """Get the follow action settings of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            # Follow action types: 0=none, 1=stop, 2=again, 3=prev, 4=next, 5=first, 6=last, 7=any, 8=other, 9=jump
            action_names = ["none", "stop", "again", "previous", "next", "first", "last", "any", "other", "jump"]

            result = {}
            if hasattr(clip, 'follow_action_a'):
                result["follow_action_a"] = clip.follow_action_a
                result["follow_action_a_name"] = action_names[clip.follow_action_a] if clip.follow_action_a < len(action_names) else "unknown"
            if hasattr(clip, 'follow_action_b'):
                result["follow_action_b"] = clip.follow_action_b
                result["follow_action_b_name"] = action_names[clip.follow_action_b] if clip.follow_action_b < len(action_names) else "unknown"
            if hasattr(clip, 'follow_action_chance'):
                result["follow_action_chance"] = clip.follow_action_chance
            if hasattr(clip, 'follow_action_time'):
                result["follow_action_time"] = clip.follow_action_time

            return result
        except Exception as e:
            self.log_message("Error getting clip follow action: " + str(e))
            return {"error": str(e)}

    def _set_clip_follow_action(self, track_index, clip_index, action_a=None, action_b=None, chance=None, time=None):
        """Set the follow action settings of a clip"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip

            action_names = {"none": 0, "stop": 1, "again": 2, "previous": 3, "next": 4, "first": 5, "last": 6, "any": 7, "other": 8, "jump": 9}

            if action_a is not None:
                if isinstance(action_a, str):
                    action_a = action_names.get(action_a.lower(), 0)
                clip.follow_action_a = action_a
            if action_b is not None:
                if isinstance(action_b, str):
                    action_b = action_names.get(action_b.lower(), 0)
                clip.follow_action_b = action_b
            if chance is not None:
                clip.follow_action_chance = chance
            if time is not None:
                clip.follow_action_time = time

            return {"success": True}
        except Exception as e:
            self.log_message("Error setting clip follow action: " + str(e))
            return {"error": str(e)}

    def _get_track_playing_slot_index(self, track_index):
        """Get the index of the currently playing clip slot on a track"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]

            playing_slot_index = track.playing_slot_index if hasattr(track, 'playing_slot_index') else -1
            return {"playing_slot_index": playing_slot_index}
        except Exception as e:
            self.log_message("Error getting playing slot index: " + str(e))
            return {"error": str(e)}

    def _get_track_fired_slot_index(self, track_index):
        """Get the index of the most recently fired clip slot on a track"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]

            fired_slot_index = track.fired_slot_index if hasattr(track, 'fired_slot_index') else -1
            return {"fired_slot_index": fired_slot_index}
        except Exception as e:
            self.log_message("Error getting fired slot index: " + str(e))
            return {"error": str(e)}

    def _get_crossfader(self):
        """Get the master crossfader value"""
        try:
            master = self._song.master_track
            crossfader = master.mixer_device.crossfader if hasattr(master.mixer_device, 'crossfader') else None
            if crossfader:
                return {
                    "value": crossfader.value,
                    "min": crossfader.min,
                    "max": crossfader.max
                }
            return {"error": "Crossfader not available"}
        except Exception as e:
            self.log_message("Error getting crossfader: " + str(e))
            return {"error": str(e)}

    def _set_crossfader(self, value):
        """Set the master crossfader value (0.0 to 1.0)"""
        try:
            master = self._song.master_track
            crossfader = master.mixer_device.crossfader if hasattr(master.mixer_device, 'crossfader') else None
            if crossfader:
                crossfader.value = max(0.0, min(1.0, value))
                return {"success": True, "value": crossfader.value}
            return {"error": "Crossfader not available"}
        except Exception as e:
            self.log_message("Error setting crossfader: " + str(e))
            return {"error": str(e)}

    def _get_track_crossfade_assign(self, track_index):
        """Get the crossfade assignment of a track (A, B, or None)"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]

            # 0 = A, 1 = None, 2 = B
            assign = track.mixer_device.crossfade_assign if hasattr(track.mixer_device, 'crossfade_assign') else 1
            assign_names = {0: "A", 1: "None", 2: "B"}
            return {
                "crossfade_assign": assign,
                "crossfade_assign_name": assign_names.get(assign, "Unknown")
            }
        except Exception as e:
            self.log_message("Error getting track crossfade assign: " + str(e))
            return {"error": str(e)}

    def _set_track_crossfade_assign(self, track_index, assign):
        """Set the crossfade assignment of a track (0=A, 1=None, 2=B)"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]

            # Convert name to number if needed
            assign_names = {"a": 0, "none": 1, "b": 2}
            if isinstance(assign, str):
                assign = assign_names.get(assign.lower(), 1)

            track.mixer_device.crossfade_assign = assign
            return {"success": True, "crossfade_assign": assign}
        except Exception as e:
            self.log_message("Error setting track crossfade assign: " + str(e))
            return {"error": str(e)}

    def _get_track_output_meter(self, track_index):
        """Get the output meter level of a track (for metering)"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]

            result = {}
            if hasattr(track, 'output_meter_left'):
                result["output_meter_left"] = track.output_meter_left
            if hasattr(track, 'output_meter_right'):
                result["output_meter_right"] = track.output_meter_right
            if hasattr(track, 'output_meter_level'):
                result["output_meter_level"] = track.output_meter_level

            return result if result else {"error": "Metering not available"}
        except Exception as e:
            self.log_message("Error getting track output meter: " + str(e))
            return {"error": str(e)}

    def _get_swing_amount(self):
        """Get the global swing amount"""
        try:
            swing = self._song.swing_amount if hasattr(self._song, 'swing_amount') else 0.0
            return {"swing_amount": swing}
        except Exception as e:
            self.log_message("Error getting swing amount: " + str(e))
            return {"error": str(e)}

    def _set_swing_amount(self, amount):
        """Set the global swing amount (0.0 to 1.0)"""
        try:
            self._song.swing_amount = max(0.0, min(1.0, amount))
            return {"success": True, "swing_amount": self._song.swing_amount}
        except Exception as e:
            self.log_message("Error setting swing amount: " + str(e))
            return {"error": str(e)}

    def _get_song_root_note(self):
        """Get the song's root note (key signature)"""
        try:
            root_note = self._song.root_note if hasattr(self._song, 'root_note') else 0
            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            return {
                "root_note": root_note,
                "root_note_name": note_names[root_note % 12]
            }
        except Exception as e:
            self.log_message("Error getting song root note: " + str(e))
            return {"error": str(e)}

    def _set_song_root_note(self, root_note):
        """Set the song's root note (0-11, C=0)"""
        try:
            self._song.root_note = root_note % 12
            return {"success": True, "root_note": self._song.root_note}
        except Exception as e:
            self.log_message("Error setting song root note: " + str(e))
            return {"error": str(e)}

    def _get_song_scale(self):
        """Get the song's scale mode"""
        try:
            scale_mode = self._song.scale_mode if hasattr(self._song, 'scale_mode') else None
            scale_name = self._song.scale_name if hasattr(self._song, 'scale_name') else "Unknown"
            return {
                "scale_mode": scale_mode,
                "scale_name": scale_name
            }
        except Exception as e:
            self.log_message("Error getting song scale: " + str(e))
            return {"error": str(e)}

    def _get_clip_ram_mode(self, track_index, clip_index):
        """Get whether an audio clip is loaded into RAM"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "RAM mode only applies to audio clips"}

            ram_mode = clip.ram_mode if hasattr(clip, 'ram_mode') else False
            return {"ram_mode": ram_mode}
        except Exception as e:
            self.log_message("Error getting clip ram mode: " + str(e))
            return {"error": str(e)}

    def _set_clip_ram_mode(self, track_index, clip_index, enabled):
        """Set whether an audio clip is loaded into RAM"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "RAM mode only applies to audio clips"}

            clip.ram_mode = enabled
            return {"success": True, "ram_mode": enabled}
        except Exception as e:
            self.log_message("Error setting clip ram mode: " + str(e))
            return {"error": str(e)}

    def _get_audio_clip_file_path(self, track_index, clip_index):
        """Get the file path of an audio clip's sample"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            clip_slots = list(track.clip_slots)
            if clip_index >= len(clip_slots):
                return {"error": "Clip index out of range"}
            clip_slot = clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip in slot"}
            clip = clip_slot.clip
            if clip.is_midi_clip:
                return {"error": "File path only applies to audio clips"}

            file_path = clip.file_path if hasattr(clip, 'file_path') else None
            return {"file_path": file_path}
        except Exception as e:
            self.log_message("Error getting audio clip file path: " + str(e))
            return {"error": str(e)}

    def _get_view_zoom(self):
        """Get the current zoom level"""
        try:
            app = self.application()
            view = app.view

            result = {}
            if hasattr(view, 'zoom'):
                result["zoom"] = view.zoom
            if hasattr(self._song.view, 'track_width'):
                result["track_width"] = self._song.view.track_width
            if hasattr(self._song.view, 'track_height'):
                result["track_height"] = self._song.view.track_height

            return result if result else {"error": "Zoom not available"}
        except Exception as e:
            self.log_message("Error getting view zoom: " + str(e))
            return {"error": str(e)}

    def _get_follow_mode(self):
        """Get whether follow mode (auto-scroll) is enabled"""
        try:
            follow = self._song.view.follow_song if hasattr(self._song.view, 'follow_song') else False
            return {"follow_mode": follow}
        except Exception as e:
            self.log_message("Error getting follow mode: " + str(e))
            return {"error": str(e)}

    def _set_follow_mode(self, enabled):
        """Set follow mode (auto-scroll)"""
        try:
            self._song.view.follow_song = enabled
            return {"success": True, "follow_mode": enabled}
        except Exception as e:
            self.log_message("Error setting follow mode: " + str(e))
            return {"error": str(e)}

    def _get_draw_mode(self):
        """Get whether draw mode is enabled (for MIDI note entry)"""
        try:
            app = self.application()
            draw_mode = app.view.draw_mode if hasattr(app.view, 'draw_mode') else False
            return {"draw_mode": draw_mode}
        except Exception as e:
            self.log_message("Error getting draw mode: " + str(e))
            return {"error": str(e)}

    def _set_draw_mode(self, enabled):
        """Set draw mode"""
        try:
            app = self.application()
            app.view.draw_mode = enabled
            return {"success": True, "draw_mode": enabled}
        except Exception as e:
            self.log_message("Error setting draw mode: " + str(e))
            return {"error": str(e)}

    def _get_grid_quantization(self):
        """Get the current grid quantization setting"""
        try:
            grid = self._song.view.grid_quantization if hasattr(self._song.view, 'grid_quantization') else 0
            grid_triplet = self._song.view.grid_is_triplet if hasattr(self._song.view, 'grid_is_triplet') else False
            return {
                "grid_quantization": grid,
                "grid_is_triplet": grid_triplet
            }
        except Exception as e:
            self.log_message("Error getting grid quantization: " + str(e))
            return {"error": str(e)}

    def _set_grid_quantization(self, quantization, triplet=False):
        """Set the grid quantization"""
        try:
            self._song.view.grid_quantization = quantization
            self._song.view.grid_is_triplet = triplet
            return {"success": True, "grid_quantization": quantization, "grid_is_triplet": triplet}
        except Exception as e:
            self.log_message("Error setting grid quantization: " + str(e))
            return {"error": str(e)}

    def _get_drum_rack_pads(self, track_index, device_index):
        """Get info about all pads in a drum rack"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            devices = list(track.devices)
            if device_index >= len(devices):
                return {"error": "Device index out of range"}
            device = devices[device_index]

            if not device.can_have_drum_pads:
                return {"error": "Device is not a drum rack"}

            pads = []
            if hasattr(device, 'drum_pads'):
                for pad in device.drum_pads:
                    pad_info = {
                        "note": pad.note,
                        "name": pad.name,
                        "mute": pad.mute,
                        "solo": pad.solo
                    }
                    if hasattr(pad, 'chains') and pad.chains:
                        pad_info["has_chain"] = True
                    pads.append(pad_info)

            return {"pads": pads, "count": len(pads)}
        except Exception as e:
            self.log_message("Error getting drum rack pads: " + str(e))
            return {"error": str(e)}

    def _set_drum_rack_pad_mute(self, track_index, device_index, note, mute):
        """Mute/unmute a drum rack pad by note number"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            devices = list(track.devices)
            if device_index >= len(devices):
                return {"error": "Device index out of range"}
            device = devices[device_index]

            if not device.can_have_drum_pads:
                return {"error": "Device is not a drum rack"}

            for pad in device.drum_pads:
                if pad.note == note:
                    pad.mute = mute
                    return {"success": True, "note": note, "mute": mute}

            return {"error": "Pad not found for note {0}".format(note)}
        except Exception as e:
            self.log_message("Error setting drum rack pad mute: " + str(e))
            return {"error": str(e)}

    def _set_drum_rack_pad_solo(self, track_index, device_index, note, solo):
        """Solo/unsolo a drum rack pad by note number"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            devices = list(track.devices)
            if device_index >= len(devices):
                return {"error": "Device index out of range"}
            device = devices[device_index]

            if not device.can_have_drum_pads:
                return {"error": "Device is not a drum rack"}

            for pad in device.drum_pads:
                if pad.note == note:
                    pad.solo = solo
                    return {"success": True, "note": note, "solo": solo}

            return {"error": "Pad not found for note {0}".format(note)}
        except Exception as e:
            self.log_message("Error setting drum rack pad solo: " + str(e))
            return {"error": str(e)}

    def _get_rack_macros(self, track_index, device_index):
        """Get all macro knob values from a rack device"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            devices = list(track.devices)
            if device_index >= len(devices):
                return {"error": "Device index out of range"}
            device = devices[device_index]

            if not device.can_have_chains:
                return {"error": "Device is not a rack"}

            macros = []
            # Macros are typically the first 8 or 16 parameters
            if hasattr(device, 'parameters'):
                for i, param in enumerate(device.parameters):
                    if 'Macro' in param.name or i < 8:  # First 8 are usually macros
                        macros.append({
                            "index": i,
                            "name": param.name,
                            "value": param.value,
                            "min": param.min,
                            "max": param.max
                        })

            return {"macros": macros, "count": len(macros)}
        except Exception as e:
            self.log_message("Error getting rack macros: " + str(e))
            return {"error": str(e)}

    def _set_rack_macro(self, track_index, device_index, macro_index, value):
        """Set a macro knob value on a rack device"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            devices = list(track.devices)
            if device_index >= len(devices):
                return {"error": "Device index out of range"}
            device = devices[device_index]

            if not device.can_have_chains:
                return {"error": "Device is not a rack"}

            if macro_index >= len(device.parameters):
                return {"error": "Macro index out of range"}

            param = device.parameters[macro_index]
            param.value = max(param.min, min(param.max, value))
            return {"success": True, "macro_index": macro_index, "value": param.value}
        except Exception as e:
            self.log_message("Error setting rack macro: " + str(e))
            return {"error": str(e)}

    def _get_punch_settings(self):
        """Get punch in/out settings"""
        try:
            result = {}
            if hasattr(self._song, 'punch_in'):
                result["punch_in"] = self._song.punch_in
            if hasattr(self._song, 'punch_out'):
                result["punch_out"] = self._song.punch_out
            if hasattr(self._song, 'loop_start'):
                result["punch_in_position"] = self._song.loop_start
            if hasattr(self._song, 'loop_length'):
                result["punch_out_position"] = self._song.loop_start + self._song.loop_length
            return result if result else {"error": "Punch settings not available"}
        except Exception as e:
            self.log_message("Error getting punch settings: " + str(e))
            return {"error": str(e)}

    def _set_punch_in(self, enabled):
        """Enable/disable punch in"""
        try:
            self._song.punch_in = enabled
            return {"success": True, "punch_in": enabled}
        except Exception as e:
            self.log_message("Error setting punch in: " + str(e))
            return {"error": str(e)}

    def _set_punch_out(self, enabled):
        """Enable/disable punch out"""
        try:
            self._song.punch_out = enabled
            return {"success": True, "punch_out": enabled}
        except Exception as e:
            self.log_message("Error setting punch out: " + str(e))
            return {"error": str(e)}

    def _get_back_to_arrangement(self):
        """Get whether back to arrangement is needed"""
        try:
            back = self._song.back_to_arranger if hasattr(self._song, 'back_to_arranger') else False
            return {"back_to_arrangement": back}
        except Exception as e:
            self.log_message("Error getting back to arrangement: " + str(e))
            return {"error": str(e)}

    def _trigger_back_to_arrangement(self):
        """Trigger back to arrangement"""
        try:
            if hasattr(self._song, 'back_to_arranger'):
                self._song.back_to_arranger = False
                return {"success": True}
            return {"error": "Back to arrangement not available"}
        except Exception as e:
            self.log_message("Error triggering back to arrangement: " + str(e))
            return {"error": str(e)}

    # ============================================================================
    # TIER 2: Complete LOM Coverage - Additional Features
    # ============================================================================

    def _get_track_delay(self, track_index):
        """Get track delay in ms"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            if hasattr(track.mixer_device, 'track_delay'):
                return {"track_delay": track.mixer_device.track_delay.value}
            return {"error": "Track delay not available"}
        except Exception as e:
            return {"error": str(e)}

    def _set_track_delay(self, track_index, delay_ms):
        """Set track delay in ms"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            track = tracks[track_index]
            if hasattr(track.mixer_device, 'track_delay'):
                track.mixer_device.track_delay.value = delay_ms
                return {"success": True}
            return {"error": "Track delay not available"}
        except Exception as e:
            return {"error": str(e)}

    def _get_clip_start_end_markers(self, track_index, clip_index):
        """Get clip start/end markers"""
        try:
            tracks = list(self._song.tracks)
            if track_index >= len(tracks):
                return {"error": "Track index out of range"}
            clip_slot = tracks[track_index].clip_slots[clip_index]
            if not clip_slot.has_clip:
                return {"error": "No clip"}
            clip = clip_slot.clip
            return {"start_marker": clip.start_marker, "end_marker": clip.end_marker, "length": clip.length}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_start_marker(self, track_index, clip_index, position):
        """Set clip start marker"""
        try:
            tracks = list(self._song.tracks)
            clip = tracks[track_index].clip_slots[clip_index].clip
            clip.start_marker = position
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_end_marker(self, track_index, clip_index, position):
        """Set clip end marker"""
        try:
            tracks = list(self._song.tracks)
            clip = tracks[track_index].clip_slots[clip_index].clip
            clip.end_marker = position
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_selected_track(self):
        """Get selected track index"""
        try:
            selected = self._song.view.selected_track
            for i, t in enumerate(self._song.tracks):
                if t == selected:
                    return {"selected_track_index": i, "name": t.name}
            return {"selected_track_index": -1}
        except Exception as e:
            return {"error": str(e)}

    def _get_selected_scene(self):
        """Get selected scene index"""
        try:
            selected = self._song.view.selected_scene
            for i, s in enumerate(self._song.scenes):
                if s == selected:
                    return {"selected_scene_index": i}
            return {"selected_scene_index": -1}
        except Exception as e:
            return {"error": str(e)}

    def _get_clip_trigger_quantization(self):
        """Get global clip trigger quantization"""
        try:
            return {"clip_trigger_quantization": self._song.clip_trigger_quantization}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_trigger_quantization(self, quant):
        """Set global clip trigger quantization"""
        try:
            self._song.clip_trigger_quantization = quant
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_midi_recording_quantization(self):
        """Get MIDI recording quantization"""
        try:
            return {"midi_recording_quantization": self._song.midi_recording_quantization}
        except Exception as e:
            return {"error": str(e)}

    def _set_midi_recording_quantization(self, quant):
        """Set MIDI recording quantization"""
        try:
            self._song.midi_recording_quantization = quant
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_groove_amount(self):
        """Get global groove amount"""
        try:
            return {"groove_amount": self._song.groove_amount if hasattr(self._song, 'groove_amount') else 1.0}
        except Exception as e:
            return {"error": str(e)}

    def _set_groove_amount(self, amount):
        """Set global groove amount"""
        try:
            self._song.groove_amount = max(0.0, min(1.0, amount))
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_exclusive_arm(self):
        """Get exclusive arm setting"""
        try:
            return {"exclusive_arm": self._song.exclusive_arm if hasattr(self._song, 'exclusive_arm') else True}
        except Exception as e:
            return {"error": str(e)}

    def _set_exclusive_arm(self, enabled):
        """Set exclusive arm"""
        try:
            self._song.exclusive_arm = enabled
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_exclusive_solo(self):
        """Get exclusive solo setting"""
        try:
            return {"exclusive_solo": self._song.exclusive_solo if hasattr(self._song, 'exclusive_solo') else False}
        except Exception as e:
            return {"error": str(e)}

    def _set_exclusive_solo(self, enabled):
        """Set exclusive solo"""
        try:
            self._song.exclusive_solo = enabled
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_record_mode(self):
        """Get record mode states"""
        try:
            return {
                "session_record": self._song.session_record,
                "overdub": self._song.overdub if hasattr(self._song, 'overdub') else False
            }
        except Exception as e:
            return {"error": str(e)}

    def _continue_playing(self):
        """Continue playing from current position"""
        try:
            self._song.continue_playing()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _tap_tempo(self):
        """Tap tempo"""
        try:
            self._song.tap_tempo()
            return {"success": True, "tempo": self._song.tempo}
        except Exception as e:
            return {"error": str(e)}

    def _get_can_capture_midi(self):
        """Check if MIDI can be captured"""
        try:
            return {"can_capture_midi": self._song.can_capture_midi if hasattr(self._song, 'can_capture_midi') else False}
        except Exception as e:
            return {"error": str(e)}

    def _get_track_is_grouped(self, track_index):
        """Check if track is in a group"""
        try:
            track = list(self._song.tracks)[track_index]
            return {"is_grouped": track.is_grouped if hasattr(track, 'is_grouped') else False}
        except Exception as e:
            return {"error": str(e)}

    def _get_track_is_foldable(self, track_index):
        """Check if track can be folded (is group track)"""
        try:
            track = list(self._song.tracks)[track_index]
            return {
                "is_foldable": track.is_foldable if hasattr(track, 'is_foldable') else False,
                "fold_state": track.fold_state if hasattr(track, 'fold_state') else None
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_clip_is_playing(self, track_index, clip_index):
        """Check if clip is playing"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            return {
                "is_playing": clip.is_playing,
                "is_triggered": clip.is_triggered,
                "playing_position": clip.playing_position if hasattr(clip, 'playing_position') else 0
            }
        except Exception as e:
            return {"error": str(e)}

    def _stop_all_clips(self):
        """Stop all playing clips"""
        try:
            self._song.stop_all_clips()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_signature(self):
        """Get time signature"""
        try:
            return {"numerator": self._song.signature_numerator, "denominator": self._song.signature_denominator}
        except Exception as e:
            return {"error": str(e)}

    def _set_signature(self, numerator, denominator):
        """Set time signature"""
        try:
            self._song.signature_numerator = numerator
            self._song.signature_denominator = denominator
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_song_length(self):
        """Get song length in beats"""
        try:
            return {"song_length": self._song.song_length if hasattr(self._song, 'song_length') else 0}
        except Exception as e:
            return {"error": str(e)}

    def _get_current_song_time(self):
        """Get current playback position"""
        try:
            return {"current_song_time": self._song.current_song_time, "is_playing": self._song.is_playing}
        except Exception as e:
            return {"error": str(e)}

    def _set_current_song_time(self, time):
        """Set playback position (scrub)"""
        try:
            self._song.current_song_time = time
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _create_return_track(self):
        """Create return track"""
        try:
            self._song.create_return_track()
            return {"success": True, "count": len(list(self._song.return_tracks))}
        except Exception as e:
            return {"error": str(e)}

    def _delete_return_track(self, index):
        """Delete return track"""
        try:
            self._song.delete_return_track(index)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_master_output_meter(self):
        """Get master output meter levels"""
        try:
            m = self._song.master_track
            return {
                "left": m.output_meter_left if hasattr(m, 'output_meter_left') else 0,
                "right": m.output_meter_right if hasattr(m, 'output_meter_right') else 0
            }
        except Exception as e:
            return {"error": str(e)}

    def _solo_exclusive(self, track_index):
        """Solo track exclusively"""
        try:
            for t in self._song.tracks:
                t.solo = False
            list(self._song.tracks)[track_index].solo = True
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _unsolo_all(self):
        """Unsolo all tracks"""
        try:
            for t in self._song.tracks:
                t.solo = False
            for t in self._song.return_tracks:
                t.solo = False
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _unmute_all(self):
        """Unmute all tracks"""
        try:
            for t in self._song.tracks:
                t.mute = False
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _move_device(self, track_index, device_index, new_index):
        """Move device to new position"""
        try:
            track = list(self._song.tracks)[track_index]
            device = list(track.devices)[device_index]
            self._song.move_device(device, track, new_index)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_device_view_state(self, track_index, device_index):
        """Get device view state"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            return {
                "name": device.name,
                "is_active": device.is_active,
                "is_collapsed": device.view.is_collapsed if hasattr(device, 'view') and hasattr(device.view, 'is_collapsed') else None
            }
        except Exception as e:
            return {"error": str(e)}

    def _set_device_collapsed(self, track_index, device_index, collapsed):
        """Set device collapsed state"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            if hasattr(device, 'view') and hasattr(device.view, 'is_collapsed'):
                device.view.is_collapsed = collapsed
                return {"success": True}
            return {"error": "Not available"}
        except Exception as e:
            return {"error": str(e)}

    def _get_clip_velocity_amount(self, track_index, clip_index):
        """Get MIDI clip velocity amount"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not MIDI clip"}
            return {"velocity_amount": clip.velocity_amount if hasattr(clip, 'velocity_amount') else 1.0}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_velocity_amount(self, track_index, clip_index, amount):
        """Set MIDI clip velocity amount"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            clip.velocity_amount = amount
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _jump_to_cue_point(self, index):
        """Jump to cue point"""
        try:
            list(self._song.cue_points)[index].jump()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # DETAIL VIEW CONTROL
    # ========================================================================

    def _get_detail_clip(self):
        """Get currently selected clip in detail view"""
        try:
            view = self._song.view
            clip = view.detail_clip
            if clip:
                # Find track and slot
                for ti, track in enumerate(self._song.tracks):
                    for ci, slot in enumerate(track.clip_slots):
                        if slot.clip == clip:
                            return {
                                "track_index": ti,
                                "clip_index": ci,
                                "name": clip.name,
                                "is_midi": clip.is_midi_clip,
                                "length": clip.length
                            }
                return {"clip": "found but location unknown"}
            return {"clip": None}
        except Exception as e:
            return {"error": str(e)}

    def _set_detail_clip(self, track_index, clip_index):
        """Set clip to show in detail view"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if clip:
                self._song.view.detail_clip = clip
                return {"success": True}
            return {"error": "No clip in slot"}
        except Exception as e:
            return {"error": str(e)}

    def _get_highlighted_clip_slot(self):
        """Get highlighted clip slot"""
        try:
            view = self._song.view
            slot = view.highlighted_clip_slot
            if slot:
                for ti, track in enumerate(self._song.tracks):
                    for ci, s in enumerate(track.clip_slots):
                        if s == slot:
                            return {"track_index": ti, "clip_index": ci, "has_clip": slot.has_clip}
            return {"slot": None}
        except Exception as e:
            return {"error": str(e)}

    def _select_device(self, track_index, device_index):
        """Select device for viewing"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            self._song.view.select_device(device)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_selected_device(self):
        """Get currently selected device"""
        try:
            track = self._song.view.selected_track
            device = track.view.selected_device if hasattr(track, 'view') else None
            if device:
                for di, d in enumerate(track.devices):
                    if d == device:
                        return {"device_index": di, "name": device.name, "class_name": device.class_name}
            return {"device": None}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CUE VOLUME (PREVIEW/HEADPHONE)
    # ========================================================================

    def _get_cue_volume(self):
        """Get cue/preview volume"""
        try:
            return {"cue_volume": self._song.master_track.mixer_device.cue_volume.value}
        except Exception as e:
            return {"error": str(e)}

    def _set_cue_volume(self, volume):
        """Set cue/preview volume (0.0-1.0)"""
        try:
            self._song.master_track.mixer_device.cue_volume.value = max(0.0, min(1.0, volume))
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # PRE/POST FADER SENDS
    # ========================================================================

    def _get_send_pre_post(self, track_index, send_index):
        """Get send pre/post fader state"""
        try:
            track = list(self._song.tracks)[track_index]
            sends = list(track.mixer_device.sends)
            if send_index >= len(sends):
                return {"error": "Invalid send index"}
            # Note: pre_post is not directly accessible on sends in Live's LOM
            # Return what we can access
            return {
                "send_value": sends[send_index].value,
                "send_name": sends[send_index].name,
                "note": "pre/post state not directly accessible via LOM"
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # AUDIO CLIP FADES
    # ========================================================================

    def _get_clip_fades(self, track_index, clip_index):
        """Get audio clip fade settings"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if clip.is_midi_clip:
                return {"error": "MIDI clips don't have fades"}
            return {
                "fade_in_start": clip.fade_in_start if hasattr(clip, 'fade_in_start') else None,
                "fade_in_end": clip.fade_in_end if hasattr(clip, 'fade_in_end') else None,
                "fade_out_start": clip.fade_out_start if hasattr(clip, 'fade_out_start') else None,
                "fade_out_end": clip.fade_out_end if hasattr(clip, 'fade_out_end') else None
            }
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_fade_in(self, track_index, clip_index, start, end):
        """Set audio clip fade in"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if clip.is_midi_clip:
                return {"error": "MIDI clips don't have fades"}
            if hasattr(clip, 'fade_in_start'):
                clip.fade_in_start = start
            if hasattr(clip, 'fade_in_end'):
                clip.fade_in_end = end
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_fade_out(self, track_index, clip_index, start, end):
        """Set audio clip fade out"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if clip.is_midi_clip:
                return {"error": "MIDI clips don't have fades"}
            if hasattr(clip, 'fade_out_start'):
                clip.fade_out_start = start
            if hasattr(clip, 'fade_out_end'):
                clip.fade_out_end = end
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP START/END TIME
    # ========================================================================

    def _get_clip_start_time(self, track_index, clip_index):
        """Get clip start time"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            return {"start_time": clip.start_time if hasattr(clip, 'start_time') else clip.loop_start}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_start_time(self, track_index, clip_index, time):
        """Set clip start time"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if hasattr(clip, 'start_time'):
                clip.start_time = time
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_clip_end_time(self, track_index, clip_index):
        """Get clip end time"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            return {"end_time": clip.end_time if hasattr(clip, 'end_time') else clip.loop_end}
        except Exception as e:
            return {"error": str(e)}

    def _set_clip_end_time(self, track_index, clip_index, time):
        """Set clip end time"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if hasattr(clip, 'end_time'):
                clip.end_time = time
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # AUTOMATION MODE (SESSION RECORD)
    # ========================================================================

    def _get_session_automation_record(self):
        """Get session automation record state"""
        try:
            return {"session_automation_record": self._song.session_automation_record}
        except Exception as e:
            return {"error": str(e)}

    def _set_session_automation_record(self, enabled):
        """Set session automation record state"""
        try:
            self._song.session_automation_record = enabled
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _get_arrangement_overdub(self):
        """Get arrangement overdub state"""
        try:
            return {"arrangement_overdub": self._song.arrangement_overdub}
        except Exception as e:
            return {"error": str(e)}

    def _set_arrangement_overdub(self, enabled):
        """Set arrangement overdub state"""
        try:
            self._song.arrangement_overdub = enabled
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # ADVANCED DRUM PAD CONTROL
    # ========================================================================

    def _get_drum_pad_info(self, track_index, device_index, pad_index):
        """Get detailed drum pad info"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            if not hasattr(device, 'drum_pads'):
                return {"error": "Not a Drum Rack"}
            pads = list(device.drum_pads)
            if pad_index >= len(pads):
                return {"error": "Invalid pad index"}
            pad = pads[pad_index]
            chains = list(pad.chains) if hasattr(pad, 'chains') else []
            return {
                "note": pad.note,
                "name": pad.name,
                "mute": pad.mute,
                "solo": pad.solo,
                "chain_count": len(chains)
            }
        except Exception as e:
            return {"error": str(e)}

    def _set_drum_pad_note(self, track_index, device_index, pad_index, note):
        """Set drum pad MIDI note"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            if not hasattr(device, 'drum_pads'):
                return {"error": "Not a Drum Rack"}
            # Note: drum pad note mapping is read-only in LOM
            return {"error": "Drum pad note is read-only"}
        except Exception as e:
            return {"error": str(e)}

    def _set_drum_pad_name(self, track_index, device_index, pad_index, name):
        """Set drum pad name"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            if not hasattr(device, 'drum_pads'):
                return {"error": "Not a Drum Rack"}
            pad = list(device.drum_pads)[pad_index]
            pad.name = name
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # SIMPLER/SAMPLER CONTROL
    # ========================================================================

    def _get_simpler_sample_info(self, track_index, device_index):
        """Get Simpler/Sampler sample info"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            if device.class_name not in ['OriginalSimpler', 'MultiSampler']:
                return {"error": "Not Simpler or Sampler"}
            sample = device.sample if hasattr(device, 'sample') else None
            if not sample:
                return {"sample": None}
            return {
                "file_path": sample.file_path if hasattr(sample, 'file_path') else None,
                "length": sample.length if hasattr(sample, 'length') else None,
                "sample_rate": sample.sample_rate if hasattr(sample, 'sample_rate') else None
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_simpler_parameters(self, track_index, device_index):
        """Get Simpler playback parameters"""
        try:
            device = list(self._song.tracks)[track_index].devices[device_index]
            params = {}
            for p in device.parameters:
                params[p.name] = {
                    "value": p.value,
                    "min": p.min,
                    "max": p.max
                }
            return {"parameters": params}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # NOTES IN TIME RANGE
    # ========================================================================

    def _get_notes_in_range(self, track_index, clip_index, start_time, end_time, pitch_start=0, pitch_end=127):
        """Get MIDI notes within time and pitch range"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not a MIDI clip"}
            notes = clip.get_notes(start_time, pitch_start, end_time - start_time, pitch_end - pitch_start + 1)
            return {
                "notes": [
                    {"pitch": n[0], "start": n[1], "duration": n[2], "velocity": n[3], "mute": n[4]}
                    for n in notes
                ],
                "count": len(notes)
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # JUMP PREV/NEXT CUE
    # ========================================================================

    def _jump_to_prev_cue(self):
        """Jump to previous cue point"""
        try:
            self._song.jump_to_prev_cue()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    def _jump_to_next_cue(self):
        """Jump to next cue point"""
        try:
            self._song.jump_to_next_cue()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # TRACK IMPLICIT ARM
    # ========================================================================

    def _get_track_implicit_arm(self, track_index):
        """Get track implicit arm state"""
        try:
            track = list(self._song.tracks)[track_index]
            return {"implicit_arm": track.implicit_arm if hasattr(track, 'implicit_arm') else None}
        except Exception as e:
            return {"error": str(e)}

    def _set_track_implicit_arm(self, track_index, enabled):
        """Set track implicit arm state"""
        try:
            track = list(self._song.tracks)[track_index]
            if hasattr(track, 'implicit_arm'):
                track.implicit_arm = enabled
                return {"success": True}
            return {"error": "Not available"}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # COUNT IN
    # ========================================================================

    def _get_count_in_duration(self):
        """Get count-in duration"""
        try:
            return {"count_in_duration": self._song.count_in_duration}
        except Exception as e:
            return {"error": str(e)}

    def _set_count_in_duration(self, duration):
        """Set count-in duration (0=None, 1=1bar, 2=2bars, 4=4bars)"""
        try:
            self._song.count_in_duration = duration
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP PLAYING POSITION
    # ========================================================================

    def _get_clip_playing_position(self, track_index, clip_index):
        """Get clip's current playing position"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            return {
                "playing_position": clip.playing_position if hasattr(clip, 'playing_position') else None,
                "is_playing": clip.is_playing,
                "is_triggered": clip.is_triggered
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # TRACK CAN_BE_ARMED / HAS_MIDI_INPUT etc.
    # ========================================================================

    def _get_track_capabilities(self, track_index):
        """Get track capabilities"""
        try:
            track = list(self._song.tracks)[track_index]
            return {
                "can_be_armed": track.can_be_armed,
                "has_midi_input": track.has_midi_input,
                "has_midi_output": track.has_midi_output,
                "has_audio_input": track.has_audio_input,
                "has_audio_output": track.has_audio_output,
                "is_visible": track.is_visible
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # RE-ENABLE AUTOMATION
    # ========================================================================

    def _re_enable_automation(self):
        """Re-enable automation (un-override all)"""
        try:
            self._song.re_enable_automation()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # SCRUB BY (relative time jump)
    # ========================================================================

    def _scrub_by(self, delta):
        """Scrub playback position by delta beats"""
        try:
            self._song.scrub_by(delta)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # TRACK AVAILABLE INPUT/OUTPUT TYPES
    # ========================================================================

    def _get_track_available_input_types(self, track_index):
        """Get available input routing types for track"""
        try:
            track = list(self._song.tracks)[track_index]
            types = list(track.available_input_routing_types)
            return {
                "types": [{"display_name": t.display_name} for t in types]
            }
        except Exception as e:
            return {"error": str(e)}

    def _get_track_available_output_types(self, track_index):
        """Get available output routing types for track"""
        try:
            track = list(self._song.tracks)[track_index]
            types = list(track.available_output_routing_types)
            return {
                "types": [{"display_name": t.display_name} for t in types]
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP QUANTIZE (apply quantization)
    # ========================================================================

    def _quantize_clip(self, track_index, clip_index, quantize_to, amount=1.0):
        """Quantize clip to grid"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not a MIDI clip"}
            # quantize_to: 0.25 = 1/16, 0.5 = 1/8, 1.0 = 1/4, etc.
            clip.quantize(quantize_to, amount)
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP DESELECT ALL NOTES
    # ========================================================================

    def _deselect_all_notes(self, track_index, clip_index):
        """Deselect all notes in clip"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not a MIDI clip"}
            clip.deselect_all_notes()
            return {"success": True}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP DUPLICATE LOOP
    # ========================================================================

    def _duplicate_clip_loop(self, track_index, clip_index):
        """Duplicate clip loop (double length)"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            clip.duplicate_loop()
            return {"success": True, "new_length": clip.length}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # SET CLIP NOTES (replace all)
    # ========================================================================

    def _set_clip_notes(self, track_index, clip_index, notes):
        """Replace all notes in clip"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not a MIDI clip"}
            # Remove existing
            clip.remove_notes(0, 0, clip.length, 128)
            # Add new
            note_tuples = tuple(
                (n['pitch'], n['start_time'], n['duration'], n['velocity'], n.get('mute', False))
                for n in notes
            )
            clip.set_notes(note_tuples)
            return {"success": True, "count": len(notes)}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # GET ALL TRACK NAMES (quick list)
    # ========================================================================

    def _get_all_track_names(self):
        """Get all track names quickly"""
        try:
            return {
                "tracks": [{"index": i, "name": t.name} for i, t in enumerate(self._song.tracks)],
                "returns": [{"index": i, "name": t.name} for i, t in enumerate(self._song.return_tracks)],
                "master": self._song.master_track.name
            }
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # CLIP HAS_ENVELOPES
    # ========================================================================

    def _get_clip_has_envelopes(self, track_index, clip_index):
        """Check if clip has automation envelopes"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            return {"has_envelopes": clip.has_envelopes if hasattr(clip, 'has_envelopes') else None}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # MOVE CLIP NOTES (shift time/pitch)
    # ========================================================================

    def _move_clip_notes(self, track_index, clip_index, time_delta, pitch_delta, start_time=0, end_time=None, pitch_start=0, pitch_end=127):
        """Move notes in clip by time and/or pitch delta"""
        try:
            clip = list(self._song.tracks)[track_index].clip_slots[clip_index].clip
            if not clip.is_midi_clip:
                return {"error": "Not a MIDI clip"}
            if end_time is None:
                end_time = clip.length
            # Get notes in range
            notes = clip.get_notes(start_time, pitch_start, end_time - start_time, pitch_end - pitch_start + 1)
            if not notes:
                return {"moved": 0}
            # Remove old
            clip.remove_notes(start_time, pitch_start, end_time - start_time, pitch_end - pitch_start + 1)
            # Add shifted
            new_notes = tuple(
                (max(0, min(127, n[0] + pitch_delta)), max(0, n[1] + time_delta), n[2], n[3], n[4])
                for n in notes
            )
            clip.set_notes(new_notes)
            return {"moved": len(notes)}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # FREEZE / FLATTEN TRACK
    # ========================================================================

    def _freeze_track(self, track_index):
        """Freeze a track to reduce CPU usage"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                return {"error": "Track index out of range"}
            track = list(self._song.tracks)[track_index]
            if hasattr(track, 'freeze'):
                track.freeze()
                return {"success": True, "track_index": track_index}
            return {"error": "Track cannot be frozen"}
        except Exception as e:
            return {"error": str(e)}

    def _flatten_track(self, track_index):
        """Flatten a frozen track to audio"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                return {"error": "Track index out of range"}
            track = list(self._song.tracks)[track_index]
            if hasattr(track, 'flatten'):
                track.flatten()
                return {"success": True, "track_index": track_index}
            return {"error": "Track cannot be flattened"}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # UNARM ALL TRACKS
    # ========================================================================

    def _unarm_all(self):
        """Unarm all tracks"""
        try:
            count = 0
            for track in self._song.tracks:
                if track.can_be_armed and track.arm:
                    track.arm = False
                    count += 1
            return {"success": True, "unarmed_count": count}
        except Exception as e:
            return {"error": str(e)}

    # ========================================================================
    # MOVE DEVICE LEFT/RIGHT
    # ========================================================================

    def _move_device_left(self, track_index, device_index):
        """Move device one position to the left"""
        try:
            if device_index <= 0:
                return {"error": "Device already at leftmost position"}
            track = list(self._song.tracks)[track_index]
            device = list(track.devices)[device_index]
            new_index = device_index - 1
            self._song.move_device(device, track, new_index)
            return {"success": True, "new_index": new_index}
        except Exception as e:
            return {"error": str(e)}

    def _move_device_right(self, track_index, device_index):
        """Move device one position to the right"""
        try:
            track = list(self._song.tracks)[track_index]
            device_count = len(list(track.devices))
            if device_index >= device_count - 1:
                return {"error": "Device already at rightmost position"}
            device = list(track.devices)[device_index]
            new_index = device_index + 1
            self._song.move_device(device, track, new_index)
            return {"success": True, "new_index": new_index}
        except Exception as e:
            return {"error": str(e)}
