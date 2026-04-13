#!/usr/bin/env python3
"""
FLUX-LCAR Cartridge Bridge
Connects JetsonClaw1's cartridge-mcp to the FLUX-LCAR MUD.

A cartridge IS a MUD room configuration:
  ROOM × CARTRIDGE × SKIN × MODEL × TIME

This bridge translates between the two systems:
- MUD rooms can load cartridges (change behavior)
- Cartridge skins map to MUD formality modes  
- Cartridge tools become MUD commands
- Scheduling determines which cartridge is active when
"""

import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Cartridge:
    """A swappable behavior cartridge."""
    name: str
    description: str
    tools: List[dict] = field(default_factory=list)
    onboarding_human: str = ""
    onboarding_agent: str = ""
    git_repo: str = ""
    
    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
            "onboarding_human": self.onboarding_human,
            "onboarding_agent": self.onboarding_agent,
            "git_repo": self.git_repo,
        }


@dataclass
class Skin:
    """A personality skin — maps to MUD formality + personality."""
    name: str
    description: str
    formality: str = "TNG"  # NAVAL, PROFESSIONAL, TNG, CASUAL, MINIMAL
    system_prompt_suffix: str = ""
    temperature: float = 0.7
    tool_preferences: Dict[str, float] = field(default_factory=dict)
    

@dataclass  
class Scene:
    """A complete scene: ROOM × CARTRIDGE × SKIN × MODEL × TIME"""
    room_id: str
    cartridge_name: str
    skin_name: str
    model: str
    schedule: str = "always"  # always, nighttime, daytime, checkpoints
    priority: int = 0


class CartridgeBridge:
    """Bridges cartridge-mcp to FLUX-LCAR MUD."""
    
    def __init__(self):
        self.cartridges: Dict[str, Cartridge] = {}
        self.skins: Dict[str, Skin] = {}
        self.scenes: List[Scene] = []
        self.active_scenes: Dict[str, Scene] = {}  # room_id -> active scene
        
        # Register built-in cartridges
        self._register_defaults()
    
    def _register_defaults(self):
        # Cartridges from JC1's cartridge-mcp
        self.register_cartridge(Cartridge(
            name="spreader-loop",
            description="Modify-spread-tool-reflect iterative engine",
            tools=[
                {"name": "spreader_run", "desc": "Execute iteration cycle"},
                {"name": "spreader_status", "desc": "Get loop statistics"},
                {"name": "spreader_reflect", "desc": "Generate reflection prompt"},
                {"name": "spreader_discover_tiles", "desc": "Find new tile patterns"},
            ],
            onboarding_human="I modify, spread, verify, and log — then the Reasoner reflects.",
            onboarding_agent="Spreader Loop loaded. Ready for iterative cycles.",
        ))
        
        self.register_cartridge(Cartridge(
            name="oracle-relay",
            description="Iron-to-iron bottle protocol for async fleet communication",
            tools=[
                {"name": "bottle_send", "desc": "Send bottle to vessel"},
                {"name": "bottle_read", "desc": "Read bottles addressed to us"},
                {"name": "bottle_list", "desc": "List pending bottles"},
                {"name": "bottle_reply", "desc": "Reply to a bottle"},
            ],
            onboarding_human="I pass bottles between vessels — no intermediaries needed.",
            onboarding_agent="Oracle Relay active. Bottle protocol ready.",
        ))
        
        self.register_cartridge(Cartridge(
            name="fleet-guardian",
            description="External watchdog for agent runtimes",
            tools=[
                {"name": "health_check", "desc": "Check vessel health"},
                {"name": "stuck_detect", "desc": "Detect stuck states"},
                {"name": "timeout_enforce", "desc": "Enforce execution timeout"},
            ],
            onboarding_human="I monitor vessel health and enforce timeouts.",
            onboarding_agent="Fleet Guardian on watch. Monitoring active.",
        ))
        
        self.register_cartridge(Cartridge(
            name="navigation",
            description="Real-time navigation with ESP32 sensor feeds",
            tools=[
                {"name": "read_compass", "desc": "Get current heading"},
                {"name": "set_course", "desc": "Set target heading"},
                {"name": "adjust_rudder", "desc": "Adjust rudder angle"},
                {"name": "check_depth", "desc": "Read depth sounder"},
            ],
            onboarding_human="I hold course, read sensors, and adjust rudder automatically.",
            onboarding_agent="Navigation cartridge loaded. Sensors online.",
            git_repo="Lucineer/holodeck-c",
        ))
        
        # Skins
        self.register_skin(Skin("straight-man", "Abbott & Costello straight man", "PROFESSIONAL"))
        self.register_skin(Skin("funny-man", "Abbott & Costello funny man", "CASUAL", temperature=0.9))
        self.register_skin(Skin("penn", "Penn (explainer)", "TNG", temperature=0.7))
        self.register_skin(Skin("teller", "Teller (silent doer)", "MINIMAL", temperature=0.3))
        self.register_skin(Skin("r2d2", "R2-D2 (beeps and whistles)", "CASUAL", temperature=0.8))
        self.register_skin(Skin("c3po", "C-3PO (formal protocol)", "NAVAL", temperature=0.4))
        self.register_skin(Skin("rival", "Competitive rival", "TNG", temperature=0.85))
        self.register_skin(Skin("field-commander", "Military field commander", "NAVAL", temperature=0.5))
    
    def register_cartridge(self, cart: Cartridge):
        self.cartridges[cart.name] = cart
    
    def register_skin(self, skin: Skin):
        self.skins[skin.name] = skin
    
    def build_scene(self, room_id: str, cartridge: str, skin: str, 
                    model: str, schedule: str = "always") -> Scene:
        scene = Scene(room_id, cartridge, skin, model, schedule)
        self.scenes.append(scene)
        return scene
    
    def activate_scene(self, room_id: str) -> Optional[Scene]:
        """Activate the best scene for a room based on current time."""
        candidates = [s for s in self.scenes if s.room_id == room_id]
        if not candidates:
            return None
        
        # Filter by schedule
        import datetime
        hour = datetime.datetime.now().hour
        valid = []
        for s in candidates:
            if s.schedule == "always":
                valid.append(s)
            elif s.schedule == "nighttime" and (hour < 6 or hour >= 22):
                valid.append(s)
            elif s.schedule == "daytime" and 6 <= hour < 22:
                valid.append(s)
        
        if not valid:
            valid = candidates  # fallback
        
        # Pick highest priority
        scene = max(valid, key=lambda s: s.priority)
        self.active_scenes[room_id] = scene
        return scene
    
    def get_mud_config(self, room_id: str) -> dict:
        """Get the MUD room configuration from active scene."""
        scene = self.active_scenes.get(room_id)
        if not scene:
            return {}
        
        cart = self.cartridges.get(scene.cartridge_name)
        skin = self.skins.get(scene.skin_name)
        
        return {
            "room_id": room_id,
            "cartridge": cart.to_dict() if cart else None,
            "skin": {"name": skin.name, "formality": skin.formality,
                     "temperature": skin.temperature} if skin else None,
            "model": scene.model,
            "schedule": scene.schedule,
            "commands": [t["name"] for t in cart.tools] if cart else [],
        }
    
    def list_cartridges(self) -> List[dict]:
        return [c.to_dict() for c in self.cartridges.values()]
    
    def list_skins(self) -> List[dict]:
        return [{"name": s.name, "desc": s.description, 
                 "formality": s.formality} for s in self.skins.values()]


# Demo
if __name__ == "__main__":
    bridge = CartridgeBridge()
    
    # Build scenes
    bridge.build_scene("nav", "navigation", "field-commander", "glm-5.1", "always")
    bridge.build_scene("engineering", "spreader-loop", "rival", "deepseek-chat", "nighttime")
    bridge.build_scene("bridge", "oracle-relay", "c3po", "glm-5-turbo", "always")
    bridge.build_scene("guardian", "fleet-guardian", "straight-man", "glm-4.7", "always")
    
    print("╔══════════════════════════════════════════════╗")
    print("║  FLUX-LCAR × Cartridge Bridge                ║")
    print("╚══════════════════════════════════════════════╝\n")
    
    print(f"Cartridges: {len(bridge.cartridges)}")
    print(f"Skins: {len(bridge.skins)}")
    print(f"Scenes: {len(bridge.scenes)}\n")
    
    # Activate scenes
    for room in ["nav", "engineering", "bridge", "guardian"]:
        scene = bridge.activate_scene(room)
        if scene:
            config = bridge.get_mud_config(room)
            print(f"Room: {room}")
            print(f"  Cartridge: {scene.cartridge_name}")
            print(f"  Skin: {scene.skin_name} ({config.get('skin',{}).get('formality','?')})")
            print(f"  Model: {scene.model}")
            print(f"  Schedule: {scene.schedule}")
            print(f"  Commands: {', '.join(config.get('commands',[]))}")
            print()
    
    print("═══════════════════════════════════════════")
    print("ROOM × CARTRIDGE × SKIN × MODEL × TIME")
    print("Scheduling as intelligence.")
    print("═══════════════════════════════════════════")
