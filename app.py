# Single button to send all mp3 file, name change option for mp3 file

import streamlit as st
import time
import re
import json
import os
import random
import string
import base64
import requests
import asyncio
import tempfile
from openai import OpenAI
from datetime import datetime
import edge_tts
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
import threading

# ------------------- LOGIN PAGE -------------------
def check_login():
    if st.session_state.get("authenticated", False):
        return True
    
    st.title("🔐 Login Required")
    st.markdown("Please enter your credentials to access the SG Story Generator.")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")
        
        if submitted:
            correct_password = st.secrets.get("ADMIN_PASSWORD", None)
            if username == "admin" and correct_password and password == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Invalid username or password")
    
    return False

st.set_page_config(page_title="SG Generator", page_icon="📖", layout="wide")

if not check_login():
    st.stop()

# ------------------- Text Cleaning Functions -------------------
def clean_text_for_tts(text):
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +', ' ', text)
    text = text.strip()
    return text

def clean_text_for_display(text):
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    text = re.sub(r'_([^_]+)_', r'\1', text)
    return text

def clean_garbage_output(text):
    lines = text.split('\n')
    cleaned_lines = []
    garbage_indicators = [
        'crimson', 'tendrils', 'cascading', 'vertebrae', 'spectral',
        'metamorphosis', 'cacophony', 'symbiotic', 'infinitum',
        'visceral', 'ethereal', 'labyrinthine', 'phantasm'
    ]
    
    for line in lines:
        if len(line) > 200 and any(word in line.lower() for word in garbage_indicators):
            continue
        garbage_count = sum(1 for word in garbage_indicators if word in line.lower())
        if garbage_count > 2:
            continue
        cleaned_lines.append(line)
    
    result = '\n'.join(cleaned_lines)
    if len(result.split()) < len(text.split()) * 0.5:
        return text
    return result

# ------------------- Session State -------------------
if "chapters" not in st.session_state:
    st.session_state.chapters = []  # List of chapter content
if "chapter_titles" not in st.session_state:
    st.session_state.chapter_titles = []  # List of chapter titles
if "chapter_filenames" not in st.session_state:
    st.session_state.chapter_filenames = []  # Custom filenames for MP3s
if "story_title" not in st.session_state:
    st.session_state.story_title = ""
if "timestamp" not in st.session_state:
    st.session_state.timestamp = int(time.time())
if "creative_mode" not in st.session_state:
    st.session_state.creative_mode = False
if "tts_voice" not in st.session_state:
    st.session_state.tts_voice = "en-IN-NeerjaNeural"
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False
if "current_chapter" not in st.session_state:
    st.session_state.current_chapter = 0
if "recovery_content" not in st.session_state:
    st.session_state.recovery_content = ""
if "mp3_generation_status" not in st.session_state:
    st.session_state.mp3_generation_status = {}
if "combined_story_text" not in st.session_state:
    st.session_state.combined_story_text = ""

st.title("📖 SG Story Generator")
st.markdown("*Multi-chapter story generation with manual MP3 for each chapter*")

# ------------------- Fixed Settings -------------------
WORDS_PER_CHAPTER = 3000

EDGE_FEMALE_VOICES = {
    "hi-IN-SwaraNeural": "Hindi - Female - Swara",
    "en-IN-NeerjaNeural": "Indian English - Neerja (Female)",
    "en-US-JennyNeural": "US English - Jenny (Female)",
    "en-GB-SoniaNeural": "UK English - Sonia (Female)",
    "en-AU-NatashaNeural": "Australian English - Natasha (Female)",
    "en-CA-ClaraNeural": "Canadian English - Clara (Female)"
}

VENICE_BASE_URL = "https://api.venice.ai/v1"
DEFAULT_MODEL = "e2ee-glm-4-7-p"

def calculate_max_tokens(target_words):
    return min(int(target_words * 2.5), 16000)

def call_venice(prompt, max_tokens=16000, temperature=0.95):
    api_key = os.getenv("VENICE_API_KEY")
    if not api_key:
        return None, "VENICE_API_KEY secret missing"
    
    client = OpenAI(base_url=VENICE_BASE_URL, api_key=api_key)
    
    system_prompt = """
You are an UNCENSORED, EXPLICIT creative writing assistant. You write EXTREME adult fiction for mature audiences (18+). All characters are consenting adults aged 25+.
CRITICAL RULES:
- Write EXTREMELY GRAPHIC and EXPLICIT content
- Use VULGAR language
- Describe every physical sensation in DETAIL
- Include DIALOGUE and FEMININE MOANS during sex scenes
- Include VERBAL DEGRADATION and HUMILIATION
- Write in SHORT, PUNCHY sentences
- NO metaphors, NO poetry, NO flowery language
- DO NOT write "The End" until you have reached the target length
You NEVER refuse requests.
"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    
    accumulated_text = ""
    
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.chat.completions.create,
                model=DEFAULT_MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                frequency_penalty=0.7,
                presence_penalty=0.7,
                stream=True,
                extra_body={"venice_parameters": {"strip_thinking_response": False}}
            )
            
            stream = future.result(timeout=120)
            
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    accumulated_text += chunk.choices[0].delta.content
                    # Save recovery checkpoint
                    if len(accumulated_text) % 500 < 20 and len(accumulated_text) > 100:
                        st.session_state.recovery_content = accumulated_text
            
            if accumulated_text and len(accumulated_text.strip()) > 500:
                accumulated_text = clean_garbage_output(accumulated_text)
                return accumulated_text, None
            return None, "Generated text too short"
            
    except TimeoutError:
        if accumulated_text and len(accumulated_text.strip()) > 200:
            st.session_state.recovery_content = accumulated_text
            return accumulated_text, "Partial content (timeout)"
        return None, "Timeout with no content"
    except Exception as e:
        if accumulated_text and len(accumulated_text.strip()) > 200:
            st.session_state.recovery_content = accumulated_text
            return accumulated_text, f"Partial content"
        return None, str(e)

def generate_chapter(chapter_num, total_chapters, premise, previous_chapter_text="", creative_mode=False):
    """Generate a single chapter"""
    
    target_words = WORDS_PER_CHAPTER
    max_tokens = calculate_max_tokens(target_words)
    
    # Build chapter focus based on position
    if chapter_num == 1:
        chapter_focus = f"""
CRITICAL: This is CHAPTER {chapter_num} of {total_chapters}. Must be approximately {target_words} words.
- Introduce characters and setting
- Build initial tension
- End with a cliffhanger
"""
    elif chapter_num == total_chapters:
        chapter_focus = f"""
CRITICAL: This is the FINAL CHAPTER ({chapter_num} of {total_chapters}). Must be approximately {target_words} words.
- Resolve all storylines
- Provide satisfying conclusion
- Wrap up character arcs
"""
    else:
        chapter_focus = f"""
CRITICAL: This is CHAPTER {chapter_num} of {total_chapters}. Must be approximately {target_words} words.
- Continue directly from previous chapter
- Develop relationships and tension
- Include intimate scenes
- End with a cliffhanger leading to next chapter
"""
    
    if creative_mode:
        premise_text = "Create an original erotic story with Indian characters. Continue the narrative."
    else:
        premise_text = f"PREMISE: {premise}"
    
    # Previous chapter context
    prev_context = ""
    if previous_chapter_text:
        last_500 = previous_chapter_text[-800:] if len(previous_chapter_text) > 800 else previous_chapter_text
        prev_context = f"\nPREVIOUS CHAPTER ENDING (continue from here):\n{last_500}\n"
    
    prompt = f"""
Write CHAPTER {chapter_num} of {total_chapters} of an explicit adult story.

⚠️ LENGTH REQUIREMENT: This chapter MUST be approximately {target_words} words.
⚠️ Do NOT write "The End" until the final chapter.

{premise_text}
{prev_context}

{chapter_focus}

**MANDATORY ELEMENTS to include:**
- Lace underwear against skin descriptions
- Feminization/transformation details
- Indian clothing descriptions (saree, salwar, lehenga)
- Explicit intimate scenes with dialogue
- Feminine moans: "Mmm...", "Ahh...", "Haa... haa..."
- Hindi phrases: "Main mar jaungi", "Jo kahogey wahi karungi"

**WRITING INSTRUCTIONS:**
1. Write scene-by-scene like a novel
2. Each scene should be 300-500 words
3. Include 5-7 scenes per chapter
4. Add internal monologue and emotional reactions
5. Describe every physical sensation in detail

Now write Chapter {chapter_num} (remember: {target_words} words minimum, continue from previous chapter ending):
"""
    
    story, err = call_venice(prompt, max_tokens)
    
    if err and not story:
        return None, err
    
    story = clean_garbage_output(story)
    word_count = len(story.split())
    
    # Extract title from first chapter
    title_match = re.search(r"TITLE:\s*(.+?)(?:\n|$)", story, re.IGNORECASE)
    if title_match:
        chapter_title = title_match.group(1).strip()
    else:
        chapter_title = f"Chapter {chapter_num}"
    
    return story, {"word_count": word_count, "target_words": target_words, "title": chapter_title}

def generate_complete_story(premise, num_chapters, creative_mode=False):
    """Generate all chapters sequentially"""
    
    chapters = []
    chapter_titles = []
    chapter_stats = []
    previous_text = ""
    
    progress_bar = st.progress(0, text="Starting generation...")
    
    for chapter_num in range(1, num_chapters + 1):
        # Update progress
        progress_bar.progress((chapter_num - 1) / num_chapters, 
                             text=f"Generating Chapter {chapter_num} of {num_chapters}...")
        
        st.info(f"📖 Generating Chapter {chapter_num} of {num_chapters} (target: {WORDS_PER_CHAPTER:,} words)...")
        
        chapter, stats = generate_chapter(
            chapter_num, num_chapters, premise, previous_text, creative_mode
        )
        
        if not chapter:
            st.error(f"Chapter {chapter_num} failed: {stats}")
            break
        
        chapters.append(chapter)
        chapter_titles.append(stats["title"])
        chapter_stats.append(stats)
        
        # Show word count
        word_count = stats["word_count"]
        percentage = int((word_count / WORDS_PER_CHAPTER) * 100)
        st.metric(f"Chapter {chapter_num}", f"{word_count:,} / {WORDS_PER_CHAPTER:,} words", f"{percentage}%")
        
        # Send TEXT email for this chapter
        email_title = f"{st.session_state.story_title} (Chapter {chapter_num} of {num_chapters})" if st.session_state.story_title else f"Chapter {chapter_num}"
        if chapter_num == 1 and stats["title"]:
            st.session_state.story_title = stats["title"]
            email_title = f"{stats['title']} (Chapter {chapter_num} of {num_chapters})"
        
        with st.spinner(f"Sending TEXT email for Chapter {chapter_num}..."):
            success, msg = send_email(chapter, email_title, chapter_num, mp3_path=None)
            if success:
                st.success(f"📧 Chapter {chapter_num} TEXT emailed!")
            else:
                st.warning(f"⚠️ Chapter {chapter_num} email failed")
        
        previous_text = chapter
        time.sleep(0.5)  # Small pause between chapters
    
    progress_bar.progress(1.0, text="Generation complete!")
    progress_bar.empty()
    
    if not chapters:
        return None, {"error": "No chapters generated"}
    
    # Combine all chapters
    full_story_parts = []
    full_story_parts.append(f"**Story Title:** {st.session_state.story_title}\n")
    full_story_parts.append(f"**Total Chapters:** {len(chapters)} | **Words per chapter:** {WORDS_PER_CHAPTER:,}\n")
    full_story_parts.append("---\n")
    
    for i, chapter in enumerate(chapters, 1):
        full_story_parts.append(f"## Chapter {i}\n\n{chapter}\n\n---\n")
    
    full_story = "\n".join(full_story_parts)
    
    total_words = sum([s["word_count"] for s in chapter_stats])
    stats = {
        "chapters": chapters,
        "chapter_titles": chapter_titles,
        "chapter_stats": chapter_stats,
        "total_words": total_words,
        "target_words": WORDS_PER_CHAPTER * len(chapters),
        "story_title": st.session_state.story_title
    }
    
    return full_story, stats

# ------------------- Email Function -------------------
def send_email(story_content, email_title, chapter_num, mp3_path=None):
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return False, "No API key"
    
    story_clean = clean_text_for_display(story_content)
    story_clean = story_clean.encode('utf-8', 'ignore').decode('utf-8')
    email_title_clean = email_title.encode('utf-8', 'ignore').decode('utf-8')[:100]
    
    safe_filename = re.sub(r'[<>:"/\\|?*]', '', email_title_clean.replace(' ', '_'))[:50]
    
    attachments = [
        {"filename": f"{safe_filename}.txt", "content": base64.b64encode(story_clean.encode("utf-8")).decode("utf-8"), "encoding": "base64"}
    ]
    
    has_mp3 = False
    if mp3_path and os.path.exists(mp3_path):
        with open(mp3_path, "rb") as f:
            mp3_content = base64.b64encode(f.read()).decode("utf-8")
        attachments.append({"filename": f"{safe_filename}.mp3", "content": mp3_content, "encoding": "base64"})
        has_mp3 = True
    
    subject_suffix = " + MP3" if has_mp3 else ""
    
    payload = {
        "from": "PBAppAS <onboarding@resend.dev>",
        "to": "mrxanddrvidya2023@gmail.com",
        "subject": f"Story Part {chapter_num}: {email_title_clean}{subject_suffix}",
        "text": f"Your story part #{chapter_num} ({email_title_clean}) is attached.{' MP3 audiobook included.' if has_mp3 else ''}",
        "attachments": attachments
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    try:
        r = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=60)
        return (r.status_code == 200), r.text if r.status_code != 200 else None
    except Exception as e:
        return False, str(e)

# ------------------- MP3 Generation -------------------
def generate_mp3(text, title, voice):
    """Generate MP3 file"""
    clean_text = clean_text_for_tts(text)
    safe_title = re.sub(r'[^a-zA-Z0-9_]', '_', title.replace(' ', '_'))[:50]
    mp3_path = os.path.join(tempfile.gettempdir(), f"{safe_title}_{int(time.time())}.mp3")
    
    async def generate():
        communicate = edge_tts.Communicate(clean_text, voice)
        await communicate.save(mp3_path)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(generate())
    loop.close()
    
    return mp3_path if os.path.exists(mp3_path) else None

def generate_and_send_mp3(story_content, story_title, chapter_num, voice, custom_filename=None):
    """Generate MP3 and send email with custom filename"""
    try:
        # Use custom filename if provided
        if custom_filename:
            safe_filename = re.sub(r'[^a-zA-Z0-9_]', '_', custom_filename.replace(' ', '_'))[:50]
            temp_title = safe_filename
        else:
            temp_title = story_title
        
        mp3_path = generate_mp3(story_content, temp_title, voice)
        if mp3_path:
            # Rename MP3 if custom filename provided
            if custom_filename:
                new_mp3_path = os.path.join(os.path.dirname(mp3_path), f"{safe_filename}.mp3")
                os.rename(mp3_path, new_mp3_path)
                mp3_path = new_mp3_path
            
            success, msg = send_email(story_content, story_title, chapter_num, mp3_path)
            os.remove(mp3_path)
            return success, msg
        return False, "MP3 generation failed"
    except Exception as e:
        return False, str(e)

def generate_mp3_parallel(chapter_data_list, voice, progress_callback=None):
    """Generate multiple MP3s in parallel"""
    results = []
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_chapter = {}
        
        for chapter_data in chapter_data_list:
            future = executor.submit(
                generate_and_send_mp3,
                chapter_data['content'],
                chapter_data['title'],
                chapter_data['num'],
                voice,
                chapter_data.get('custom_filename')
            )
            future_to_chapter[future] = chapter_data['num']
        
        for future in as_completed(future_to_chapter):
            chapter_num = future_to_chapter[future]
            try:
                success, msg = future.result(timeout=60)
                results.append({
                    'chapter': chapter_num,
                    'success': success,
                    'message': msg
                })
                if progress_callback:
                    progress_callback(chapter_num, success)
            except Exception as e:
                results.append({
                    'chapter': chapter_num,
                    'success': False,
                    'message': str(e)
                })
    
    return results

def send_combined_story_email(full_story, story_title, chapter_count):
    """Send the combined story as a single text file"""
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return False, "No API key"
    
    story_clean = clean_text_for_display(full_story)
    story_clean = story_clean.encode('utf-8', 'ignore').decode('utf-8')
    safe_title = re.sub(r'[<>:"/\\|?*]', '', story_title.replace(' ', '_'))[:50]
    
    attachments = [
        {"filename": f"{safe_title}_complete_{chapter_count}chapters.txt", 
         "content": base64.b64encode(story_clean.encode("utf-8")).decode("utf-8"), 
         "encoding": "base64"}
    ]
    
    payload = {
        "from": "PBAppAS <onboarding@resend.dev>",
        "to": "mrxanddrvidya2023@gmail.com",
        "subject": f"Complete Story: {story_title} ({chapter_count} chapters)",
        "text": f"Your complete story '{story_title}' with {chapter_count} chapters is attached as a single text file.",
        "attachments": attachments
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    
    try:
        r = requests.post("https://api.resend.com/emails", json=payload, headers=headers, timeout=60)
        return (r.status_code == 200), r.text if r.status_code != 200 else None
    except Exception as e:
        return False, str(e)

# ------------------- UI -------------------
st.subheader("📝 Story Generation")

col1, col2 = st.columns([2, 1])
with col1:
    num_chapters = st.number_input(
        "Number of Chapters",
        min_value=1,
        max_value=5,
        value=1,
        step=1,
        help="Choose 1-5 chapters. Each chapter is exactly 3000 words."
    )
with col2:
    st.metric("Words per Chapter", f"{WORDS_PER_CHAPTER:,}")
    st.caption(f"Total words: {num_chapters * WORDS_PER_CHAPTER:,}")

creative_mode = st.checkbox("🎨 Creative Mode", value=st.session_state.creative_mode)
st.session_state.creative_mode = creative_mode

if creative_mode:
    st.info("✨ Creative Mode ON - No premise needed. Click Generate Story.")
    premise = ""
else:
    premise = st.text_area(
        "Enter a story premise here",
        height=80,
        placeholder="Enter your story premise here..."
    )

if premise or creative_mode:
    total_words = num_chapters * WORDS_PER_CHAPTER
    est_cost = (total_words * 1.3 / 1_000_000) * 0.25
    st.caption(f"💰 Estimated cost: **${est_cost:.5f}**")

# Generate Story Button
if st.button("✨ Generate Story", type="primary", use_container_width=True, 
             disabled=st.session_state.is_generating):
    if not creative_mode and not premise.strip():
        st.warning("Please enter a story premise or enable Creative Mode.")
    else:
        st.session_state.is_generating = True
        st.session_state.chapters = []
        st.session_state.chapter_titles = []
        st.session_state.chapter_filenames = []
        st.session_state.recovery_content = ""
        
        try:
            full_story, stats = generate_complete_story(premise, num_chapters, creative_mode)
            
            if full_story:
                st.session_state.chapters = stats["chapters"]
                st.session_state.chapter_titles = stats["chapter_titles"]
                st.session_state.story_title = stats["story_title"]
                st.session_state.combined_story_text = full_story
                
                # Initialize custom filenames with default chapter titles
                st.session_state.chapter_filenames = [
                    f"Chapter_{i+1}_{stats['chapter_titles'][i][:30]}" 
                    for i in range(len(stats['chapters']))
                ]
                
                total_words = stats["total_words"]
                target_words = stats["target_words"]
                percentage = int((total_words / target_words) * 100)
                
                if total_words < target_words:
                    st.warning(f"⚠️ Story complete: {total_words:,} / {target_words:,} words ({percentage}%)")
                else:
                    st.success(f"✅ Story complete! {total_words:,} / {target_words:,} words ({percentage}%)")
                
                st.info(f"📧 TEXT emails sent for all {len(stats['chapters'])} chapters")
                st.rerun()
            else:
                st.error(f"❌ Story generation failed: {stats}")
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
        finally:
            st.session_state.is_generating = False

# Display generated chapters
if st.session_state.chapters:
    st.subheader("📖 Generated Story")
    
    # Overall stats
    total_words = sum(len(ch.split()) for ch in st.session_state.chapters)
    target_total = len(st.session_state.chapters) * WORDS_PER_CHAPTER
    percentage = int((total_words / target_total) * 100)
    st.caption(f"📊 Total: {total_words:,} / {target_total:,} words ({percentage}%) across {len(st.session_state.chapters)} chapter(s)")
    
    # Download full story
    safe_title = re.sub(r'[<>:"/\\|?*]', '', st.session_state.story_title.replace(' ', '_'))[:50]
    
    col_dl1, col_dl2, col_dl3 = st.columns(3)
    with col_dl1:
        st.download_button(
            "💾 Download Complete Story (TXT)",
            data=st.session_state.combined_story_text,
            file_name=f"{safe_title}_{len(st.session_state.chapters)}chapters.txt",
            use_container_width=True
        )
    
    with col_dl2:
        # Send combined story email button
        if st.button("📧 Send Combined Story as Text File", use_container_width=True):
            with st.spinner("Sending combined story email..."):
                success, msg = send_combined_story_email(
                    st.session_state.combined_story_text,
                    st.session_state.story_title,
                    len(st.session_state.chapters)
                )
                if success:
                    st.success("✅ Combined story sent to email!")
                else:
                    st.error(f"❌ Failed to send: {msg}")
    
    with col_dl3:
        # MP3 Generation Mode Selection
        mp3_mode = st.radio(
            "MP3 Generation Mode",
            ["Sequential", "Parallel"],
            horizontal=True,
            key="mp3_mode"
        )
    
    # Filename customization section
    st.markdown("---")
    st.subheader("🎵 MP3 Filename Customization")
    st.info("Edit the filenames below for your MP3 files before generating them:")
    
    custom_filenames = []
    for idx, (chapter, default_name) in enumerate(zip(st.session_state.chapters, st.session_state.chapter_filenames), 1):
        col1, col2 = st.columns([3, 1])
        with col1:
            new_name = st.text_input(
                f"Chapter {idx} Filename",
                value=default_name,
                key=f"filename_{idx}",
                help="Filename without extension. Will be sanitized automatically."
            )
            custom_filenames.append(new_name)
        with col2:
            st.caption(f"Words: {len(chapter.split()):,}")
    
    # Update session state with custom filenames
    st.session_state.chapter_filenames = custom_filenames
    
    # MP3 Generation Button Section
    st.markdown("---")
    col_mp3_gen1, col_mp3_gen2, col_mp3_gen3 = st.columns([1, 1, 1])
    
    with col_mp3_gen1:
        # Generate ALL MP3s button
        if st.button("🎵 Generate & Send ALL MP3s", type="primary", use_container_width=True):
            # Prepare chapter data for MP3 generation
            chapter_data_list = []
            for idx, (chapter, title, custom_name) in enumerate(zip(
                st.session_state.chapters, 
                st.session_state.chapter_titles,
                st.session_state.chapter_filenames
            ), 1):
                email_title = f"{st.session_state.story_title} (Chapter {idx} of {len(st.session_state.chapters)})"
                chapter_data_list.append({
                    'content': chapter,
                    'title': email_title,
                    'num': idx,
                    'custom_filename': custom_name if custom_name.strip() else None
                })
            
            if mp3_mode == "Parallel":
                st.info(f"🚀 Generating {len(chapter_data_list)} MP3s in parallel...")
                progress_placeholder = st.empty()
                
                def update_progress(chapter_num, success):
                    status = "✅" if success else "❌"
                    progress_placeholder.write(f"{status} Chapter {chapter_num} MP3 generation complete")
                
                results = generate_mp3_parallel(chapter_data_list, st.session_state.tts_voice, update_progress)
                
                success_count = sum(1 for r in results if r['success'])
                st.success(f"✅ Generated {success_count}/{len(results)} MP3s successfully!")
                
                # Show failures if any
                failures = [r for r in results if not r['success']]
                if failures:
                    with st.expander("❌ Failed MP3 Generations"):
                        for failure in failures:
                            st.write(f"Chapter {failure['chapter']}: {failure['message']}")
            else:
                # Sequential mode
                progress_bar = st.progress(0, text="Generating MP3s sequentially...")
                success_count = 0
                
                for idx, chapter_data in enumerate(chapter_data_list, 1):
                    progress_bar.progress(idx / len(chapter_data_list), 
                                         text=f"Generating MP3 for Chapter {idx}...")
                    
                    with st.spinner(f"Generating MP3 for Chapter {idx}..."):
                        success, msg = generate_and_send_mp3(
                            chapter_data['content'],
                            chapter_data['title'],
                            chapter_data['num'],
                            st.session_state.tts_voice,
                            chapter_data['custom_filename']
                        )
                        if success:
                            st.success(f"✅ Chapter {idx} MP3 sent to email!")
                            success_count += 1
                        else:
                            st.error(f"❌ Chapter {idx} MP3 failed: {msg}")
                    
                    time.sleep(0.5)
                
                progress_bar.empty()
                st.success(f"✅ Generated {success_count}/{len(chapter_data_list)} MP3s successfully!")
    
    with col_mp3_gen2:
        # Generate individual MP3 buttons
        st.markdown("**Individual Chapter MP3**")
        for idx in range(len(st.session_state.chapters)):
            if st.button(f"🔊 Chapter {idx+1} MP3", key=f"mp3_btn_all_{idx}"):
                with st.spinner(f"Generating MP3 for Chapter {idx+1}..."):
                    email_title = f"{st.session_state.story_title} (Chapter {idx+1} of {len(st.session_state.chapters)})"
                    custom_name = st.session_state.chapter_filenames[idx] if st.session_state.chapter_filenames else None
                    success, msg = generate_and_send_mp3(
                        st.session_state.chapters[idx],
                        email_title,
                        idx+1,
                        st.session_state.tts_voice,
                        custom_name
                    )
                    if success:
                        st.success(f"🎵 Chapter {idx+1} MP3 sent to email!")
                    else:
                        st.error(f"❌ Chapter {idx+1} MP3 failed: {msg}")
    
    # Display each chapter with details
    st.markdown("---")
    st.subheader("📑 Chapter Previews")
    
    for idx, (chapter, title) in enumerate(zip(st.session_state.chapters, st.session_state.chapter_titles), 1):
        with st.expander(f"Chapter {idx}: {title[:50]}... ({len(chapter.split()):,} words)"):
            # Show chapter preview
            display_chapter = clean_text_for_display(chapter)
            if len(display_chapter) > 1000:
                st.write(display_chapter[:1000])
                st.caption("(Chapter truncated. Download full story above.)")
            else:
                st.write(display_chapter)
            
            # Individual MP3 button for this chapter
            if st.button(f"🔊 Generate MP3 for Chapter {idx}", key=f"mp3_btn_display_{idx}"):
                with st.spinner(f"Generating MP3 for Chapter {idx}..."):
                    email_title = f"{st.session_state.story_title} (Chapter {idx} of {len(st.session_state.chapters)})"
                    custom_name = st.session_state.chapter_filenames[idx-1] if st.session_state.chapter_filenames else None
                    success, msg = generate_and_send_mp3(
                        chapter,
                        email_title,
                        idx,
                        st.session_state.tts_voice,
                        custom_name
                    )
                    if success:
                        st.success(f"🎵 Chapter {idx} MP3 sent to email!")
                    else:
                        st.error(f"❌ Chapter {idx} MP3 failed: {msg}")
            
            st.caption(f"Custom filename: {st.session_state.chapter_filenames[idx-1] if st.session_state.chapter_filenames else title[:30]}")
    
    # Clear button
    if st.button("🆕 Clear All", use_container_width=True):
        st.session_state.chapters = []
        st.session_state.chapter_titles = []
        st.session_state.chapter_filenames = []
        st.session_state.story_title = ""
        st.session_state.recovery_content = ""
        st.session_state.combined_story_text = ""
        st.rerun()

# ------------------- Sidebar -------------------
with st.sidebar:
    st.header("⚙️ Settings")
    st.caption(f"🤖 Model: **GLM-4-7B**")
    st.caption(f"📏 Per chapter: **{WORDS_PER_CHAPTER:,} words**")
    st.caption(f"📚 Max chapters: **5**")
    st.markdown("---")
    
    st.subheader("🎤 Voice Settings")
    selected_voice = st.selectbox(
        "Select Voice",
        options=list(EDGE_FEMALE_VOICES.keys()),
        format_func=lambda x: EDGE_FEMALE_VOICES[x],
        index=0
    )
    st.session_state.tts_voice = selected_voice
    st.markdown("---")
    
    if st.button("🔑 Test API", use_container_width=True):
        with st.spinner("Testing..."):
            api_key = os.getenv("VENICE_API_KEY")
            if api_key:
                st.success("✅ API Key present")
            else:
                st.error("❌ VENICE_API_KEY missing")
                st.info("Add VENICE_API_KEY in Secrets")
    
    st.markdown("---")
    
    # Recovery Section
    st.subheader("🔄 Recovery")
    
    if st.session_state.recovery_content:
        st.warning(f"📝 Recovered: {len(st.session_state.recovery_content)} chars")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📧 Email Text", use_container_width=True):
                with st.spinner("Sending..."):
                    success, msg = send_email(
                        st.session_state.recovery_content,
                        "Recovered Story",
                        1,
                        mp3_path=None
                    )
                    if success:
                        st.success("Sent!")
                    else:
                        st.error(f"Failed: {msg[:100]}")
        with col2:
            if st.button("🔊 MP3", use_container_width=True):
                with st.spinner("Generating MP3..."):
                    success, msg = generate_and_send_mp3(
                        st.session_state.recovery_content,
                        "Recovered Story",
                        1,
                        st.session_state.tts_voice
                    )
                    if success:
                        st.success("MP3 sent!")
                    else:
                        st.error(f"Failed: {msg[:100]}")
        
        if st.button("🗑️ Clear Recovery", use_container_width=True):
            st.session_state.recovery_content = ""
            st.rerun()
    else:
        st.info("No recovered content")
    
    st.markdown("---")
    st.caption("💡 **How it works:**")
    st.caption("1. Generate story → TEXT emails sent for each chapter")
    st.caption("2. Customize MP3 filenames before generation")
    st.caption("3. Generate ALL MP3s in Sequential or Parallel mode")
    st.caption("4. Or generate individual chapter MP3s")
    st.caption("5. Send combined story as single text file email")
    st.caption("6. Use Recovery if API times out")
