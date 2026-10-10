import { AppShell } from '@/components/app-shell';
import { GenerationCenter } from '@/components/generation-center';
import { ClothGenerationCenter } from '@/components/cloth-generation-center';

export default function GenerationPage() {
  return <AppShell current="generation"><div className="space-y-10"><nav className="flex gap-5"><a href="#cube-generation" className="text-primary">方块轨迹生成</a><a href="#cloth-generation" className="text-primary">衣物外观生成</a></nav><section id="cube-generation"><GenerationCenter /></section><section id="cloth-generation"><ClothGenerationCenter /></section></div></AppShell>;
}
