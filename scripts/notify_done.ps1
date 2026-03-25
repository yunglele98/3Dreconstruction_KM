param([int]$ProcessId)

try {
    # Wait for the python process to finish
    Wait-Process -Id $ProcessId -ErrorAction Stop
    
    # Notify the user with voice
    Add-Type -AssemblyName System.speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.Speak("The image processing job has completed.")
    
    # Also pop up a message box just in case speakers are off
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show("The Gemini vision model has finished processing all images!", "Job Complete")
} catch {
    # Process might have already exited
}
