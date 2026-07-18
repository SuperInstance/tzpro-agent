# 🔬 Open-Source Repo Research for tzpro-agent / CoCapn Ecosystem

> Generated: 2026-07-17 | Deep research sweep across sonar AI, edge ML, marine CV, multi-agent IoT, Bayesian tools, fleet management, and trending agentic/fishing repos.

---

## 1. 🐟 Sonar / Fish Finding AI

### 1.1 Echopype — Ocean Sonar Data Processing
- **Repo:** https://github.com/echostack-org/echopype
- **What:** Open-source Python package for interoperable, scalable processing of ocean sonar (echosounder) data — converts proprietary vendor formats to standardized netCDF/Zarr, enabling ML-ready pipelines for fish/krill abundance estimation.
- **Insight:** Standardization of heterogeneous sonar formats is the critical first step before any ML pipeline; CoCapn's echogram ingestion needs a similar "universal parser" layer.

### 1.2 Echostack — Scalable Echosounder Suite
- **Repo:** https://github.com/echostack-org (org-level; core processing and viz tools)
- **What:** Flexible, scalable open-source Python suite for detection, classification, and quantification of fish and zooplankton from echosounder data across diverse ocean observing platforms.
- **Insight:** Modular pipeline architecture (ingest → process → classify → visualize) mirrors what CoCapn needs for end-to-end sonar analysis; adopt the "pluggable processing stage" pattern.

### 1.3 Imaging-Sonar-Fish-Detection — YOLOv7 for Sonar
- **Repo:** https://github.com/meerap1/Imaging-Sonar-Fish-Detection
- **What:** YOLOv7 model trained on 1500+ sonar images for fish detection and localization in marine environments, with curated positive/negative image datasets.
- **Insight:** YOLOv7 on sonar imagery proves that off-the-shelf object detectors work on non-optical data; CoCapn can bootstrap with pretrained YOLO backbones fine-tuned on sonar echograms.

### 1.4 OBSEA Fish Detection — YOLOv8 Underwater Observatory
- **Repo:** https://github.com/ai4os-hub/obsea-fish-detection
- **What:** YOLOv8-based fish detection and classification model fine-tuned for the OBSEA underwater observatory, shipped as a Docker container for easy deployment.
- **Insight:** Docker-containerized ML models enable one-command deployment on edge hardware — CoCapn agents should follow the same "model-as-container" pattern.

### 1.5 open_echo — Arduino SONAR System
- **Repo:** https://github.com/neumi/open_echo
- **What:** Open-source echo sounder / depth sounder / SONAR system built on Arduino with a Python interface for live echogram viewing and parameter control.
- **Insight:** Ultra-low-cost hardware sonar is feasible; CoCapn could target sub-$100 sonar platforms for widespread fleet deployment rather than relying on expensive commercial fishfinders.

### 1.6 Fish Detection AI (NOAA/DOE) — Faster R-CNN on Sonar
- **Repo:** https://github.com/stevengutstein/FishDetectionAI (primary author; also on MHKDR)
- **What:** Faster R-CNN trained on Alaska Fish & Game sonar images for fish identification, tracking, and counting at marine energy facilities, with unsupervised domain adaptation to transfer across sonar types.
- **Insight:** Domain adaptation techniques are essential for deploying one trained model across different sonar hardware — CoCapn must plan for model transferability from day one.

---

## 2. ⚡ Edge ML for Maritime

### 2.1 VIAME — Video/Image Analytics for Marine Environments
- **Repo:** https://github.com/VIAME/VIAME
- **What:** NOAA/Kitware's flagship open-source computer vision toolkit for do-it-yourself AI: object detection, tracking, annotation, size measurement, and model generation for fisheries stock assessment and marine science (BSD-3 license).
- **Insight:** VIAME's "low-code GUI + deep ML backend" architecture is the gold standard for marine computer vision tooling — CoCapn should offer a similar spectrum from no-code to full-code.

### 2.2 Microsoft EdgeML — Lightweight ML Algorithms
- **Repo:** https://github.com/Microsoft/EdgeML
- **What:** Suite of ML algorithms (Bonsai, ProtoNN, FastGRNN) specifically designed for edge devices with extreme constraints on storage, latency, and energy — targeting MCUs and embedded systems.
- **Insight:** Bonsai/predictive tree algorithms provide a template for how CoCapn could run fish species classifiers on microcontrollers on the boat itself, not in the cloud.

### 2.3 MIT HAN Lab TinyML — Memory-Efficient Inference
- **Repo:** https://github.com/mit-han-lab/tinyml
- **What:** MIT research project on TinyML: system-algorithm co-design for running deep learning on IoT/microcontroller-class hardware with aggressive memory optimization.
- **Insight:** The TinyML approach of model compression + hardware-aware architecture search is directly applicable to running CoCapn's inference on power-constrained buoys and sonar modules.

### 2.4 MLPerf Tiny — Embedded ML Benchmarking
- **Repo:** https://github.com/mlcommons/tiny
- **What:** Industry-standard benchmark suite for ML inference on extremely low-power devices (microcontrollers, <100KB RAM), with reference implementations in TensorFlow Lite Micro.
- **Insight:** Standardized benchmarks let CoCapn objectively compare model choices for edge deployment; adopt MLPerf Tiny as the evaluation framework for on-boat model selection.

### 2.5 UOD-YOLO — Lightweight Underwater Object Detection
- **Repo:** https://github.com/cug-mrs/UOD-YOLO (search: "UOD-YOLO lightweight marine detection")
- **What:** Lightweight real-time detection framework derived from YOLOv11n, optimized for detecting marine organisms in complex underwater environments on resource-constrained platforms.
- **Insight:** Proof that modern YOLO variants can be shrunk for marine edge deployment; CoCapn should benchmark UOD-YOLO against standard YOLO for on-boat fish detection.

---

## 3. 📷 Open-Source Marine Computer Vision

### 3.1 Marine Detect (Orange Open Source) — YOLOv8 Species ID
- **Repo:** https://github.com/Orange-OpenSource/marine-detect
- **What:** Two YOLOv8 object detection models identifying 17 marine bio-indicator species (fish + invertebrates) plus megafauna (sharks, turtles, rays) from underwater cameras, developed with Tēnaka for coral reef monitoring.
- **Insight:** Dual-model architecture (common species + rare megafauna) is smart — CoCapn should separate "catch species" detection from "bycatch/protected species" detection for different accuracy requirements.

### 3.2 Fish Detection, Tracking, and Classification — Full Pipeline
- **Repo:** https://github.com/carlos-vf/Fish-Detection-Tracking-and-Classification
- **What:** Complete computer vision pipeline using YOLOv8 for real-time multi-species fish detection, unique-ID tracking across frames, and classification in underwater video — with buffered and real-time modes.
- **Insight:** The detection→tracking→classification pipeline with per-instance IDs is exactly the architecture CoCapn needs for counting fish per-species over time in video feeds.

### 3.3 Fish-Detection-YOLOv8 — Species Detection
- **Repo:** https://github.com/Vinay0905/Fish-Detection-YOLOv8
- **What:** YOLOv8-based fish species detection model with training/evaluation/deployment tooling, optimized for real-time marine biology and population monitoring applications.
- **Insight:** Clean separation of "train" / "eval" / "deploy" scripts is a simple but effective pattern CoCapn should replicate for reproducible model lifecycle management.

### 3.4 YOLO-Fish — Darknet Underwater Detection
- **Repo:** https://github.com/tamim662/YOLO-Fish
- **What:** Robust real-time fish detection model implemented in Darknet framework, designed for diverse underwater marine environments.
- **Insight:** Darknet-based models are often lighter than PyTorch equivalents, making them a candidate for CoCapn's most resource-constrained edge nodes.

### 3.5 OpenFish (AusOcean) — Go-Based Marine Classification
- **Repo:** https://github.com/ausocean/openfish
- **What:** Open-source system written in Go for classifying marine species from video/image data, with manual and automatic annotation, search, and ML-based species statistics (under active development).
- **Insight:** Using Go for marine CV is unconventional but yields single-binary deployment with no Python dependency hell — relevant for CoCapn's embedded deployment strategy.

### 3.6 Underwater Animal Detection — YOLOv8 Multi-Class
- **Repo:** https://github.com/HarishValliappan/Underwater-Animal-Detection
- **What:** YOLOv8 model achieving 97.12% accuracy on 7 underwater animal classes (fish, jellyfish, penguin, puffin, shark, starfish, stingray) with a custom dataset.
- **Insight:** High-accuracy multi-class underwater detection is achievable with modest custom datasets — CoCapn should prioritize dataset curation for its specific target species.

### 3.7 Kraken — Aquaculture Fish Counting System
- **Repo:** Published via SBC 2023 proceedings (search: "Kraken fish detection TensorFlow Raspberry Pi")
- **What:** Open-source computational system integrating TensorFlow, YOLO, OpenCV, Arduino, and Raspberry Pi for automated fish detection, counting, and size estimation in turbid freshwater aquaculture environments, achieving 90% classification accuracy.
- **Insight:** The full-stack integration of "ML model + commodity hardware + domain-specific preprocessing" for turbid water is directly applicable to CoCapn's real-world fishing conditions.

---

## 4. 🤖 Multi-Agent Systems for IoT

### 4.1 IoT-Agent (NTU MARS) — LLM Reasoning from Sensor Data
- **Repo:** https://github.com/NTUMARS/IoT-Agent
- **What:** Framework that enhances LLM reasoning on real-world IoT sensor data using RAG (hybrid embedding + BM25 retrieval + cross-encoder re-ranking) with support for local models like LLaMA2 and Mistral.
- **Insight:** The RAG pipeline for sensor reasoning is a blueprint for how CoCapn agents could interpret raw sonar + GPS + environmental sensor streams using on-device small LLMs.

### 4.2 Microsoft Edge AI for Beginners — Agentic IoT
- **Repo:** https://github.com/microsoft/edgeai-for-beginners
- **What:** Course and project suite for building intelligent edge AI agents and multi-agent orchestration targeting 100% local deployment on resource-limited IoT devices with no cloud dependency.
- **Insight:** "100% local, no cloud" is the operational requirement for CoCapn — fishing boats have intermittent connectivity at best; all agent intelligence must run offline-first.

### 4.3 IoT-SkillsBench — Skills-Based Agentic AI for Embedded
- **Repo:** https://github.com/iot-agent/iot-skillsbench
- **What:** Skills-based agentic AI framework for developing embedded/IoT systems, enabling LLM agents to build code for real hardware (Arduino, ESP32-S3) with structured domain knowledge injection.
- **Insight:** The "skills as structured knowledge" approach maps directly to CoCapn's idea of specialized fishing agents (sonar agent, navigation agent, catch-logging agent) with domain-specific capabilities.

### 4.4 CrewAI — Multi-Agent Orchestration
- **Repo:** https://github.com/crewAIInc/crewAI
- **What:** Production framework for orchestrating role-based AI agents that collaborate on tasks — agents have defined roles, goals, tools, and can delegate to each other with structured inter-agent communication.
- **Insight:** The role-based agent model (Captain, Navigator, Sonar Operator, Deckhand) maps naturally to a fishing vessel crew; CrewAI's delegation patterns model real bridge resource management.

### 4.5 LangGraph — Stateful Agent Workflows
- **Repo:** https://github.com/langchain-ai/langgraph
- **What:** Framework for building controllable, stateful agent systems with support for single-agent, multi-agent, hierarchical, and sequential control flows, with built-in persistence and streaming.
- **Insight:** LangGraph's state-machine approach to agent orchestration provides the deterministic control CoCapn needs for safety-critical maritime operations where probabilistic agent behavior is unacceptable.

### 4.6 Microsoft AutoGen (AG2) — Conversational Multi-Agent
- **Repo:** https://github.com/microsoft/autogen
- **What:** Multi-agent conversation framework where agents communicate via structured chat to solve complex tasks, with support for code execution, human-in-the-loop, and nested chat hierarchies.
- **Insight:** The "conversation as coordination" paradigm is interesting for CoCapn's human-in-the-loop use cases where the captain needs to converse with AI agents through natural language on the bridge.

---

## 5. 📊 Bayesian / Probabilistic Programming

### 5.1 SMILE — Statistical Machine Intelligence & Learning Engine
- **Repo:** https://github.com/haifengl/smile
- **What:** High-performance ML framework in C++/Java with explicit mobile/Android support, low memory footprint, and built-in Bayesian network inference — used by BayesMobile for on-device Bayesian reasoning.
- **Insight:** On-device Bayesian inference is production-proven on mobile; CoCapn can use SMILE for Laplace-smoothed species probability estimates directly on the boat's edge hardware.

### 5.2 NumPyro — JAX-Based Probabilistic Programming
- **Repo:** https://github.com/pyro-ppl/numpyro
- **What:** Pyro's probabilistic programming on JAX with GPU/TPU acceleration, Hamiltonian Monte Carlo, and variational inference — models exportable to TFLite for mobile/edge deployment.
- **Insight:** The JAX→TFLite export path means NumPyro Bayesian models can be trained on powerful hardware and deployed on CoCapn's edge devices, giving the best of both worlds.

### 5.3 AutoPPL — C++ Compile-Time Probabilistic Programming
- **Repo:** https://github.com/JamesYang007/autoppl
- **What:** C++ template library for probabilistic programming with compile-time optimizations, efficient memory usage, and high-performance inference — suitable for embedded systems.
- **Insight:** Compile-time optimized C++ probabilistic inference is the most resource-efficient approach for running Bayesian models on CoCapn's lowest-power sensor nodes.

### 5.4 PyMC — Bayesian Modeling with MCMC/Variational Inference
- **Repo:** https://github.com/pymc-devs/pymc
- **What:** Python probabilistic programming for Bayesian statistical modeling with advanced MCMC and variational inference; models with JAX backend can follow the JAX→TFLite path for edge deployment.
- **Insight:** PyMC's rich ecosystem of priors and likelihoods is ideal for prototyping CoCapn's species distribution models before compressing them for edge deployment.

---

## 6. 🚢 Fleet Management / Maritime Intelligence

### 6.1 AISdb — AIS Data Management & ML Platform
- **Repo:** https://github.com/MAPS-Lab/AISdb
- **What:** Open-source Python package for storing, retrieving, analyzing, and visualizing AIS vessel tracking data with seamless integration into the Python ML ecosystem for model development.
- **Insight:** AISdb's clean data pipeline (ingest → validate → store → analyze → model) is a template for how CoCapn should handle vessel telemetry and fishing activity data across the fleet.

### 6.2 Global Fishing Watch — Vessel Classification & Fishing Detection
- **Repo:** https://github.com/GlobalFishingWatch/vessel-classification
- **What:** Feature generation and ML model training/inference for classifying vessels and detecting fishing behavior from AIS movement patterns, with additional repos on fishing footprint analysis.
- **Insight:** GFW's fishing behavior classification from trajectory data is directly reusable for CoCapn's fleet activity monitoring and anomaly detection on fishing patterns.

### 6.3 HarborFlow — Maritime GIS + AI Intelligence
- **Repo:** https://github.com/Michela999/HarborFlow_Maritime_GIS_AI_Analysis
- **What:** Independent maritime data intelligence system combining AIS tracking, GIS analytics, and ML for vessel behavior interpretation, port congestion analysis, and anomaly detection.
- **Insight:** HarborFlow's anomaly detection on vessel behavior is relevant for CoCapn's fleet monitoring — detecting when a fishing vessel deviates from its normal operating pattern.

### 6.4 Edgehog — IoT Device Fleet Manager
- **Repo:** https://github.com/edgehog-device-manager/edgehog
- **What:** Open-source device manager for IoT fleet lifecycle management: real-time device status, OTA updates, Docker app management, geolocation, and GraphQL API — built on Elixir/Astarte.
- **Insight:** Edgehog's OTA update and Docker app management approach is ideal for CoCapn's heterogeneous fleet of edge devices across different vessel types and hardware.

### 6.5 Fleet (FleetDM) — Universal Device Management
- **Repo:** https://github.com/fleetdm/fleet
- **What:** Open-source platform for MDM, patching, software deployment, and verification across all major OS platforms including Linux IoT devices — with strong diagnostics and compliance features.
- **Insight:** Fleet's osquery-based device visibility approach could give CoCapn unified monitoring of all vessel edge nodes regardless of underlying hardware/OS.

### 6.6 SeeSea — Vessel Traffic Services
- **Repo:** https://github.com/erikk03/seeSea
- **What:** Open-source VTS application for real-time vessel tracking using AIS data, with zone violation alerts, fleet management, and maritime situational awareness.
- **Insight:** Zone-based geofencing with alerts is directly applicable to CoCapn's fishing zone compliance monitoring — detect when vessels enter/exit regulated fishing areas.

---

## 7. 🎣 Smart Fishing / Aquaculture

### 7.1 Open-Source Fish Farming Prototypes — LoRaWAN Water Quality
- **Repo:** https://github.com/open-pisciculture/open-source-fish-farming-prototypes
- **What:** Open-source, low-cost buoy prototype for remote monitoring of water quality (temperature, pH, dissolved oxygen) in fish farming, transmitting via LoRaWAN to cloud storage/visualization.
- **Insight:** LoRaWAN-based telemetry from floating buoys to cloud is a proven pattern CoCapn can adopt for environmental data collection from remote fishing grounds with no cellular coverage.

### 7.2 SMART-FISH-FARMING — IoT Pond Management
- **Repo:** https://github.com/zakiganda/SMART-FISH-FARMING-WITH-IoT-Fish.net-
- **What:** IoT-based fish pond monitoring system that automatically detects and reacts to poor water quality conditions (pH, water level) to prevent disease in aquaculture operations.
- **Insight:** Automated environmental alerting with configurable thresholds is essential for CoCapn's catch-quality monitoring — the same pattern applies to hold temperature, time-in-hold, and water quality.

---

## 8. 🔬 Research & Platform Adjacent

### 8.1 MultitaskAIS / GeoTrackNet — Maritime Anomaly Detection
- **Repo:** https://github.com/duonginspace/MultitaskAIS
- **What:** Multi-task deep learning architecture for maritime surveillance using AIS data, with GeoTrackNet module for probabilistic neural network representations of vessel tracks and anomaly detection.
- **Insight:** Probabilistic trajectory modeling is a powerful approach for CoCapn to detect anomalous fishing behavior (e.g., illegal fishing patterns, transshipment at sea).

### 8.2 Edge Engine (IFRA IoT) — Industrial IoT Edge
- **Repo:** https://github.com/ifraiot/edge-engine
- **What:** Container-based industrial IoT edge computing platform supporting MQTT, OPC UA, Modbus, NATS streaming for data processing, analytics, and visualization at the edge.
- **Insight:** Protocol-agnostic edge data ingestion (MQTT/Modbus/NATS) is exactly what CoCapn needs to interface with diverse onboard sensors (sonar, GPS, engine telemetry, environmental).

### 8.3 Fleetbase FleetOps — Logistics Fleet Management
- **Repo:** https://github.com/fleetbase/fleetops
- **What:** Core logistics and fleet management extension with dispatch console, telematics integration, route intelligence, and analytics dashboards for live fleet visibility.
- **Insight:** The dispatch console + telematics integration pattern is reusable for CoCapn's fleet coordination dashboard — view all vessels, assign fishing grounds, monitor catch in real-time.

---

## 📋 Summary Statistics

| Domain | Repos Found | Key Theme |
|--------|-------------|-----------|
| Sonar / Fish Finding AI | 6 | YOLO + echogram processing + domain adaptation |
| Edge ML for Maritime | 5 | TinyML + model compression + marine-specific optimization |
| Marine Computer Vision | 7 | YOLOv8 dominance + tracking pipelines + species classification |
| Multi-Agent for IoT | 6 | RAG for sensors + role-based agents + offline-first |
| Bayesian / Probabilistic | 4 | On-device inference + JAX→TFLite export + C++ compile-time |
| Fleet Management / AIS | 6 | AIS data + vessel classification + fleet OTA management |
| Smart Fishing / Aquaculture | 2 | LoRaWAN telemetry + water quality monitoring |
| Research / Platform | 3 | Trajectory anomaly detection + edge protocols + fleet dashboards |
| **TOTAL** | **39** | |

---

## 🎯 Top 5 Most Actionable Repos for CoCapn

1. **VIAME** — Production-grade marine CV toolkit with NOAA backing; fork and customize for CoCapn's species
2. **Echopype** — The standard for sonar data ingestion; adopt its format conversion layer
3. **NTUMARS/IoT-Agent** — RAG-on-sensors pipeline is the closest existing project to CoCapn's agent architecture
4. **CrewAI** — Role-based multi-agent orchestration maps perfectly to vessel crew roles
5. **Edgehog** — Fleet-scale OTA device management for the heterogeneous CoCapn edge hardware

---

## 🔗 Quick-Reference Link List

```
# Sonar AI
https://github.com/echostack-org/echopype
https://github.com/meerap1/Imaging-Sonar-Fish-Detection
https://github.com/ai4os-hub/obsea-fish-detection
https://github.com/neumi/open_echo
https://github.com/stevengutstein/FishDetectionAI

# Edge ML / Marine CV
https://github.com/VIAME/VIAME
https://github.com/Microsoft/EdgeML
https://github.com/mit-han-lab/tinyml
https://github.com/Orange-OpenSource/marine-detect
https://github.com/carlos-vf/Fish-Detection-Tracking-and-Classification
https://github.com/Vinay0905/Fish-Detection-YOLOv8
https://github.com/tamim662/YOLO-Fish
https://github.com/ausocean/openfish
https://github.com/HarishValliappan/Underwater-Animal-Detection

# Multi-Agent / IoT
https://github.com/NTUMARS/IoT-Agent
https://github.com/microsoft/edgeai-for-beginners
https://github.com/iot-agent/iot-skillsbench
https://github.com/crewAIInc/crewAI
https://github.com/langchain-ai/langgraph
https://github.com/microsoft/autogen

# Bayesian / Probabilistic
https://github.com/haifengl/smile
https://github.com/pyro-ppl/numpyro
https://github.com/JamesYang007/autoppl
https://github.com/pymc-devs/pymc

# Fleet / Maritime Intelligence
https://github.com/MAPS-Lab/AISdb
https://github.com/GlobalFishingWatch/vessel-classification
https://github.com/Michela999/HarborFlow_Maritime_GIS_AI_Analysis
https://github.com/edgehog-device-manager/edgehog
https://github.com/fleetdm/fleet
https://github.com/erikk03/seeSea
https://github.com/duonginspace/MultitaskAIS
https://github.com/ifraiot/edge-engine
https://github.com/fleetbase/fleetops

# Smart Fishing / Aquaculture
https://github.com/open-pisciculture/open-source-fish-farming-prototypes
https://github.com/zakiganda/SMART-FISH-FARMING-WITH-IoT-Fish.net-
https://github.com/mlcommons/tiny
```
