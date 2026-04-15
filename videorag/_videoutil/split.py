import os
import time
import shutil
import numpy as np
from tqdm import tqdm
from moviepy.video import fx as vfx
from moviepy.video.io.VideoFileClip import VideoFileClip
from .._utils import logger

def split_video(
    video_path,
    working_dir,
    segment_length,
    num_frames_per_segment,
    audio_output_format='mp3',
):  
    video_name = os.path.basename(video_path).split('.')[0]
    # Use a stable timestamp (based on file size/time or just fixed) for resuming
    unique_timestamp = "stable" 
    video_segment_cache_path = os.path.join(working_dir, '_cache', video_name)
    
    segment_index2name, segment_times_info = {}, {}
    
    # Check if we can reuse existing cache
    if os.path.exists(video_segment_cache_path):
        logger.info(f"Cache folder exists for {video_name}, checking for existing segments...")
        # Basic check: if we have files, we might be able to resume
        if os.listdir(video_segment_cache_path):
             logger.info(f"Found existing segments in {video_segment_cache_path}. Attempting to reconstruct metadata...")
             # We still need to open the video to get durations/times for consistency
    else:
        os.makedirs(video_segment_cache_path, exist_ok=True)
    
    segment_index = 0
    segment_index2name, segment_times_info = {}, {}
    with VideoFileClip(video_path) as video:
    
        total_video_length = int(video.duration)
        start_times = list(range(0, total_video_length, segment_length))
        # if the last segment is shorter than 5 seconds, we merged it to the last segment
        if len(start_times) > 1 and (total_video_length - start_times[-1]) < 5:
            start_times = start_times[:-1]
        
        for start in tqdm(start_times, desc=f"Spliting Video {video_name}"):
            if start != start_times[-1]:
                end = min(start + segment_length, total_video_length)
            else:
                end = total_video_length
            
            subvideo = video.subclip(start, end)
            subvideo_length = subvideo.duration
            frame_times = np.linspace(0, subvideo_length, num_frames_per_segment, endpoint=False)
            frame_times += start
            
            segment_index2name[f"{segment_index}"] = f"{unique_timestamp}-{segment_index}-{start}-{end}"
            segment_times_info[f"{segment_index}"] = {"frame_times": frame_times, "timestamp": (start, end)}
            
            # save audio
            audio_file_base_name = segment_index2name[f"{segment_index}"]
            audio_file = f'{audio_file_base_name}.{audio_output_format}'
            audio_full_path = os.path.join(video_segment_cache_path, audio_file)
            
            if os.path.exists(audio_full_path):
                # Skip if already exists
                segment_index += 1
                continue

            try:
                subaudio = subvideo.audio
                subaudio.write_audiofile(audio_full_path, codec='mp3', verbose=False, logger=None)
            except Exception as e:
                logger.warning(f"Warning: Failed to extract audio for video {video_name} ({start}-{end}). Probably due to lack of audio track.")

            segment_index += 1

    return segment_index2name, segment_times_info

def saving_video_segments(
    video_name,
    video_path,
    working_dir,
    segment_index2name,
    segment_times_info,
    error_queue,
    video_output_format='mp4',
):
    try:
        with VideoFileClip(video_path) as video:
            video_segment_cache_path = os.path.join(working_dir, '_cache', video_name)
            for index in tqdm(segment_index2name, desc=f"Saving Video Segments {video_name}"):
                start, end = segment_times_info[index]["timestamp"][0], segment_times_info[index]["timestamp"][1]
                video_file = f'{segment_index2name[index]}.{video_output_format}'
                subvideo = video.subclip(start, end)
                subvideo.write_videofile(os.path.join(video_segment_cache_path, video_file), codec='libx264', verbose=False, logger=None)
    except Exception as e:
        error_queue.put(f"Error in saving_video_segments:\n {str(e)}")
        raise RuntimeError