import { useCallback, useState } from 'react';
import { studioRegenerate, studioRun, getJob } from '../services/api';
import { EngineJob } from '../types';

/** Same pollJob shape as api.ts's pollJob, duplicated locally only so a failed regenerate
 * can update `error` without clobbering the last-good `output` — pollJob's single return
 * value doesn't let a caller distinguish "still have old output" from "job failed". */
async function poll(jobId: string, onProgress?: (job: EngineJob) => void, intervalMs = 1000): Promise<EngineJob> {
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const job = await getJob(jobId);
    onProgress?.(job);
    if (job.status === 'done' || job.status === 'failed') return job;
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}

/** Shared run/regenerate/poll lifecycle for every STUDIO tool screen. Every tool run goes
 * through jobs.py (uniform code path), so this hook is the one place that knows how to
 * drive that — individual tool components just call run()/regenerate() and render output. */
export function useStudioRun<T = any>() {
  const [output, setOutput] = useState<T | null>(null);
  const [running, setRunning] = useState(false);
  const [job, setJob] = useState<EngineJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [regeneratingBlock, setRegeneratingBlock] = useState<string | null>(null);

  const run = useCallback(async (toolId: string, inputs: Record<string, any>, useVoiceProfile: boolean = true) => {
    setRunning(true);
    setError(null);
    setJob(null);
    try {
      const { job_id } = await studioRun(toolId, inputs, useVoiceProfile);
      const finished = await poll(job_id, setJob);
      if (finished.status === 'failed') {
        setError(finished.error || 'Run failed.');
      } else {
        setOutput(finished.result as T);
      }
    } catch (err: any) {
      setError(err.message || 'Run failed.');
    } finally {
      setRunning(false);
    }
  }, []);

  const regenerate = useCallback(async (runId: string, block: string) => {
    setRegeneratingBlock(block);
    setError(null);
    try {
      const { job_id } = await studioRegenerate(runId, block);
      const finished = await poll(job_id);
      if (finished.status === 'failed') {
        setError(finished.error || 'Regenerate failed.');
      } else if (finished.result) {
        setOutput(finished.result as T);
      }
    } catch (err: any) {
      setError(err.message || 'Regenerate failed.');
    } finally {
      setRegeneratingBlock(null);
    }
  }, []);

  const reset = useCallback(() => {
    setOutput(null);
    setError(null);
    setJob(null);
  }, []);

  return { output, setOutput, running, job, error, run, regenerate, regeneratingBlock, reset };
}
