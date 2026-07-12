import { Config } from "@remotion/cli/config";

// Render rápido e com boa qualidade para long-form 16:9.
Config.setVideoImageFormat("jpeg");
Config.setPixelFormat("yuv420p");
Config.setCodec("h264");
Config.setConcurrency(null); // usa todos os núcleos disponíveis
Config.overrideWebpackConfig((c) => c);
