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
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
};

export type Dataset = {
  id: number;
  name: string;
  root_path: string;
  session_count: number;
  episode_count: number;
  accepted_count: number;
  created_at: string;
};

export type Episode = {
  id: number;
  session_id: string;
  dataset_id: number;
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
  format: 'lerobot' | 'openpi_lerobot_v21' | 'rlds' | 'robomimic';
  status: string;
  output_path: string;
  error: string | null;
  output_name: string | null;
  repo_id: string | null;
  images: number | null;
  profile: 'physical_joint8' | 'openpi_franka_joint8' | 'fastwam_franka_joint8' | null;
  episode_count: number;
  episode_ids: number[];
  created_at: string;
};

export type ConsumerSmoke = {
  id: string;
  export_id: string;
  consumer: 'openpi' | 'fastwam';
  status: 'queued' | 'running' | 'passed' | 'failed';
  report_path: string;
  log_path: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  report: {
    weight_forward?: {
      weights_loaded: boolean;
      model_forward_passed: boolean;
      contract_compatible?: boolean;
      deployment_compatible: boolean;
      closed_loop_validated?: boolean;
      training_evidence?: string;
      actions?: { shape: number[] | null; dtype: string | null };
      policy_infer_ms?: number;
      compatibility_reason?: string;
    };
  } | null;
  report_read_error?: string;
};
