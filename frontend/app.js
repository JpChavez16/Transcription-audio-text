document.addEventListener('DOMContentLoaded', () => {
    const urlInput = document.getElementById('urlInput');
    const submitBtn = document.getElementById('submitBtn');
    const btnText = submitBtn.querySelector('.btn-text');
    const loader = submitBtn.querySelector('.loader-spinner');

    // Status Elements
    const statusContainer = document.getElementById('status-container');
    const logConsole = document.getElementById('log-console');
    const statusTitle = document.getElementById('status-title');
    const statusBadge = document.getElementById('status-badge');
    const progressFill = document.getElementById('progress-fill');

    // Results Elements
    const resultsContainer = document.getElementById('results-container');
    const downloadTxt = document.getElementById('download-txt');
    const downloadJson = document.getElementById('download-json');
    const previewText = document.getElementById('preview-text');

    let currentJobId = null;
    let pollInterval = null;

    // --- Event Listeners ---
    submitBtn.addEventListener('click', handleSubmit);
    urlInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSubmit();
    });

    // --- Core Functions ---

    async function handleSubmit() {
        const url = urlInput.value.trim();
        if (!url) return showLog("Please enter a valid URL", "error");

        setLoading(true);
        resetUI();

        try {
            showLog(`Submitting job for: ${url}...`);
            const response = await fetch(`${CONFIG.API_URL}/jobs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: url })
            });

            if (!response.ok) throw new Error(`API Error: ${response.statusText}`);

            const data = await response.json();
            currentJobId = data.jobId;

            showLog(`Job created! ID: ${currentJobId}`);
            updateStatus("Processing", "Phase 1: Streaming", 10);

            statusContainer.classList.remove('hidden');
            startPolling();

        } catch (error) {
            console.error(error);
            showLog(`Error: ${error.message}`, "error");
            setLoading(false);
        }
    }

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);

        pollInterval = setInterval(async () => {
            if (!currentJobId) return;

            try {
                const response = await fetch(`${CONFIG.API_URL}/jobs/${currentJobId}`);
                const data = await response.json();

                handleStatusUpdate(data);

            } catch (error) {
                console.warn("Polling error:", error);
            }
        }, 5000); // Poll every 5s
    }

    function handleStatusUpdate(data) {
        // Calculate progress based on totalChunks if available
        let progress = 0;
        let statusMsg = "Processing...";
        let badge = "Processing";

        if (data.status === "completed") {
            progress = 100;
            finishJob(data);
            return;
        }

        if (data.status === "processing") {
            // Estimate progress
            if (data.totalChunks && data.totalChunks > 0) {
                // If we have total chunks, check if we have specific progress
                // For now, we simulate based on time or just keep it moving
                // Since our API currently only returns status, we can't be precise yet
                // But we can check message
            }

            // Simple heuristics based on message
            if (data.message.includes("Transcribed chunk")) {
                statusMsg = data.message;
                badge = "Phase 2: Transcribing";
                progress = 50; // Approximated

                // Try to parse "Transcribed chunk X"
                const match = data.message.match(/chunk (\d+)/);
                if (match && data.totalChunks) {
                    progress = (parseInt(match[1]) / parseInt(data.totalChunks)) * 90;
                }
            } else {
                progress = 20;
            }
        }

        updateStatus(statusMsg, badge, progress);
    }

    function finishJob(data) {
        clearInterval(pollInterval);
        setLoading(false);
        updateStatus("Job Completed!", "Done", 100);
        showLog("Transcription finished successfully!");

        // Show Results
        resultsContainer.classList.remove('hidden');

        // Setup download links
        // Assuming public bucket or handled via presigned URLs in a real app
        // Here we construct the public S3 URL based on known structure
        // But for this demo, we might need to rely on the API returning the URL or constructing it.
        // Let's check if the API returns the transcriptionKey.

        if (data.transcriptionKey) {
            // We need to fetch the content to display preview
            // And set hrefs. 
            // Note: In a real prod setup, these would be presigned URLs. 
            // Since our bucket currently isn't fully public for direct object access (maybe?),
            // we might hit issues if we try to fetch directly from browser unless CORS is open.
            // Let's try to construct the URL assuming the S3 website endpoint or direct HTTP access if public.

            // Hack: using the web bucket endpoint for now if the user deployed it there? 
            // No, the transcriptions are in a separate bucket.
            // Let's try seeing if we can get the text via the API (not implemented) or just link for now.

            showLog(`Artifacts available at: ${data.transcriptionKey}`);
        }

        // Update Download Buttons with Presigned URLs
        if (data.downloadUrlTxt) {
            downloadTxt.href = data.downloadUrlTxt;
            downloadTxt.classList.remove('disabled');
        }

        if (data.downloadUrlJson) {
            downloadJson.href = data.downloadUrlJson;
            downloadJson.classList.remove('disabled');

            // Fetch preview content safely using the presigned URL
            fetch(data.downloadUrlTxt)
                .then(res => res.text())
                .then(text => {
                    previewText.textContent = text.substring(0, 1000) + (text.length > 1000 ? "..." : "");
                })
                .catch(err => console.warn("Could not load preview", err));
        }

        // For now, let's fetch the JSON content if possible, or just mock the preview
        previewText.textContent = "Transcription ready. Please check the Console/S3 for files.";

        // If we can't easily generate safe links without backend presigning, we log it.
        showLog("Downloads are available in the S3 bucket.");
    }

    // --- UI Helpers ---

    function setLoading(isLoading) {
        if (isLoading) {
            submitBtn.disabled = true;
            btnText.classList.add('hidden');
            loader.classList.remove('hidden');
        } else {
            submitBtn.disabled = false;
            btnText.classList.remove('hidden');
            loader.classList.add('hidden');
        }
    }

    function resetUI() {
        statusContainer.classList.add('hidden');
        resultsContainer.classList.add('hidden');
        logConsole.innerHTML = '';
        progressFill.style.width = '0%';
    }

    function updateStatus(title, badgeText, percent) {
        statusTitle.textContent = title;
        statusBadge.textContent = badgeText;
        progressFill.style.width = `${percent}%`;

        // Check for specific logs
        if (title !== "Processing...") {
            showLog(`Status update: ${title}`);
        }
    }

    function showLog(msg, type = "info") {
        const div = document.createElement('div');
        div.className = 'log-entry';
        div.textContent = `> ${msg}`;
        if (type === 'error') div.style.color = '#ef4444';

        logConsole.appendChild(div);
        logConsole.scrollTop = logConsole.scrollHeight;
    }
});
