from pydub import AudioSegment
import gradio as gr
from utils.audio_utils import *
from config import *
# ----------------------------
# Gradio UI (main)
# ----------------------------
js_func = """
function refresh() {
    const url = new URL(window.location);

    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.href = url.href;
    }
}
"""
with open("styles.css", "r") as f:
    css_content = f.read()
with gr.Blocks(js=js_func, css=css_content, theme=gr.themes.Soft(primary_hue="blue")) as demo:
    gr.Markdown("# 🎧 Stem Studio — Edit Panel")

    # State
    state_uploaded = gr.State(None)
    state_stems: gr.State = gr.State({})
    original_stems: gr.State = gr.State({})
    state_mix: gr.State = gr.State(None)

    # STEP 1 - Upload & preview
    with gr.Row():
        file_input = gr.File(type="filepath", label="Upload a Song")
        url_input = gr.Textbox(label="Or Use YouTube URL", visible=False)
    with gr.Row():
        process_button = gr.Button("Process")        
    with gr.Row():
        in_audio = gr.Audio(label="Your Song", type="filepath", sources=[], interactive=True)
    output_file = gr.File(label="Downloaded/Uploaded Song", visible=False)

    in_audio.change(
        fn=update_trimmed_audio,
        inputs=in_audio,
        outputs=None
    )
    # STEP 2 - Choose stems to include (initial)
    with gr.Group():
        choose = gr.CheckboxGroup(choices=STEM_ORDER, value=DEFAULT_INCLUDE, label="Include in initial mix")

    # STEP 3 - Drumstick
    with gr.Group():
        with gr.Row():
            add_stick = gr.Checkbox(label="Add drumstick before song", value=False)
        with gr.Row():
            stick_preview_audio = gr.Audio(label="Drumstick preview", type="filepath", interactive=False, value= export_temp_wav(AudioSegment.from_file(DEFAULT_STICK_PATH).set_frame_rate(DEFAULT_SR), prefix="stick_"))

    # STEP 4 - Create mix
    with gr.Group():
        with gr.Row():
            run_btn = gr.Button("Create Mix", variant="primary")
        with gr.Row():
            result_audio = gr.Audio(label="Result", type="filepath", interactive=False, show_share_button= True)
        with gr.Row():
            out_file = gr.File(label="Download link", interactive=False, visible=False)
            btn_edit = gr.Button("Edit Stems", visible=False)
            new_song_btn = gr.Button("🎵 New Song", variant="secondary", visible=False)
        status_msg = gr.Markdown("")
    use_mock = gr.State(False)
    process_button.click(fn=handle_input, inputs=[file_input, url_input], outputs=[output_file, state_uploaded, in_audio, use_mock]).then(
        fn=lambda f, u: gr.update(visible=(f is not None or u is not None)),
        inputs=[file_input, url_input],
        outputs=new_song_btn
    )

    

    run_btn.click(
        do_separate_and_mix,
        inputs=[state_uploaded, choose, add_stick, use_mock],
        outputs=[result_audio, state_stems, state_mix, out_file, status_msg],
    ).then(
        fn=lambda f: gr.update(visible=(f is not None)),
        inputs=[result_audio],
        outputs=btn_edit
    )

    # STEP 5 - Edit panel (stacked stems)
    with gr.Group(visible=False) as edit_panel:
        gr.Markdown("### Edit: all stems (stacked). Toggle include / preview / silence / gain")


        edit_status = gr.Markdown("")

        # Build stacked UI
        for s in STEM_ORDER:
            with gr.Group(elem_classes="stem-panel"):
                with gr.Row():
                    per_include[s] = gr.Checkbox(label=f"Include {s}", value=(s in DEFAULT_INCLUDE))
                    per_reset_btn[s] = gr.Button(f"Reset {s}", variant="secondary")
                with gr.Row():                   
                    per_player[s] = gr.Audio(label=f"{s} preview", type="filepath", interactive=False, show_download_button = True)
                with gr.Row():
                    per_start[s] = gr.Textbox(label=f"{s} - silence start (mm:ss or seconds)", placeholder="e.g. 00:10", value="")
                    per_end[s] = gr.Textbox(label=f"{s} - silence end (mm:ss or seconds) — leave empty to end", placeholder="e.g. 00:25", value="")
                    per_silence_btn[s] = gr.Button(f"Silence on {s}", variant="secondary")
                with gr.Row():
                    per_gain[s] = gr.Slider(label=f"{s} gain (dB)", minimum=-18, maximum=18, value=0, step=0.5)
                    per_gain_btn[s] = gr.Button(f"Apply gain to {s}", variant="secondary")


        # Rebuild area
        with gr.Group():
            with gr.Row():
                rebuild_btn = gr.Button("Recreate Mix From Edited Stems", variant="primary")
            with gr.Row():
                edited_result = gr.Audio(label="Edited Result", type="filepath", interactive=False, show_share_button=True)
            with gr.Row():    
                edited_download = gr.File(label="Download edited mix", interactive=False, visible=False)

    
    # Build outputs list for btn_edit binding: first edit_panel visibility, then for each stem: player, include, start, end, gain
    edit_outputs = [edit_panel]
    for s in STEM_ORDER:
        edit_outputs += [per_player[s], per_include[s], per_start[s], per_end[s], per_gain[s]]

    btn_edit.click(populate_edit_ui, inputs=[state_stems, choose, gr.State(True)], outputs=edit_outputs + [original_stems])
    
    new_song_btn.click(
            fn=new_song,
            inputs=[choose],
            outputs=[file_input, url_input, in_audio, output_file, state_uploaded, state_stems, state_mix, result_audio, out_file, add_stick, new_song_btn, btn_edit, edited_download, *edit_outputs],
        )
    new_song_btn.click(
        None, js="() => { window.scrollTo({ top: 0, behavior: 'smooth' }); }"
    )
    
    # Wire buttons for each stem
    for s in STEM_ORDER:
        per_silence_btn[s].click(
            apply_silence_for_stem,
            inputs=[state_stems, gr.State(s), per_start[s], per_end[s]],
            outputs=[state_stems, per_player[s], edit_status],
        )
        per_gain_btn[s].click(
            apply_gain_for_stem,
            inputs=[state_stems, gr.State(s), per_gain[s]],
            outputs=[state_stems, per_player[s], edit_status],
        )
        per_reset_btn[s].click(
            reset_stem,  
            inputs=[state_stems, original_stems, gr.State(s)],
            outputs=[per_include[s], per_start[s], per_end[s], per_gain[s], per_player[s], edit_status]
        )

    rebuild_btn.click(
        rebuild_from_edited,
        inputs=[state_stems,
                per_include["vocals"], per_include["guitar"], per_include["piano"],
                per_include["drums"], per_include["bass"], per_include["other"],
                add_stick],
        outputs=[edited_result, edited_download],
    ) 
    

if __name__ == "__main__":
    demo.launch()
