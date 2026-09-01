export type Session = {
  id: string;
  dataset_id: number;
  dataset_name?: string;
  adapter_id: string;
  engine_id: 'genesis' | 'isaac_sim';
  scene_id: string;
  control_mode: 'keyboard' | 'gello';
  status: string;
  target_episodes: number;
  collector_url: string;
  worker_pid: number | null;
  episode_count?: number;
  accepted_count?: number;
  pending_count?: number;
  config: Record<string, unknown>;
};

export type Episode = {
  id: number;
  session_id: string;
  episode_uuid: string;
  path: string;
  task: string;
  operator_success: number | null;
  auto_success: number | null;
  qa_status: 'pending' | 'accepted' | 'rejected';
  failure_reason: string | null;
  num_frames: number;
  created_at: string | null;
  manifest?: { camera_names?: string[]; fps?: number; episode_metrics?: Record<string, unknown> };
  trajectory?: Record<string, number[] | number[][]>;
};

export type ExportJob = {
  id: string;
  dataset_id: number;
  format: 'lerobot' | 'rlds' | 'robomimic';
  status: string;
  output_path: string;
  error: string | null;
  created_at: string;
};
