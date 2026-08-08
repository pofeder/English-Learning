window.AIJobs = (() => {
    const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

    async function wait(jobId, onStatus) {
        const maxAttempts = 180;
        for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
            const resp = await fetch("/api/ai/jobs/" + encodeURIComponent(jobId));
            const job = await resp.json();
            if (!resp.ok) throw new Error(job.error || "任务不存在");
            if (typeof onStatus === "function") onStatus(job.status);
            if (job.status === "succeeded") return job.result;
            if (job.status === "failed") throw new Error(job.error || "AI 批改失败");
            await sleep(1000);
        }
        throw new Error("AI 批改超时，请稍后查看结果");
    }

    return { wait };
})();
