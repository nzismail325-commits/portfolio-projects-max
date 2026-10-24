<template>
  <div class="love-tree-container">
    <div class="effects-layer">
      <!-- 关怀值特效 -->
      <div v-if="health >= 5 ? false : false"></div>
      <div v-if="care >= 5" class="care-effects">
        <div :class="['life-particles', careLevelClass]">
          <div v-for="n in lifeParticleCount" :key="`life-${n}`" class="life-particle"></div>
        </div>
        <div v-if="care >= 20" :class="['falling-petals', careLevelClass]">
          <div
            v-for="n in petalCount"
            :key="`petal-${n}`"
            class="petal"
            :style="petalStyle()"
          ></div>
        </div>
      </div>

      <!-- 陪伴值特效 -->
      <div v-if="companion >= 5" class="companion-effects">
        <div :class="['butterflies', companionLevelClass]">
          <div
            v-for="n in butterflyCount"
            :key="`butterfly-${n}`"
            class="butterfly"
            :style="butterflyStyle()"
          >🦋</div>
        </div>
        <div
          v-if="companion >= 21"
          :class="['guardian-shield', companionLevelClass]"
          :style="{ transform: `translate(-50%, -50%) scale(${shieldScale})` }"
        ></div>
      </div>

      <!-- 甜蜜值特效 -->
      <div v-if="sweetness >= 5" class="sweetness-effects">
        <div :class="['fireflies', sweetnessLevelClass]">
          <div
            v-for="n in fireflyCount"
            :key="`firefly-${n}`"
            class="firefly"
            :style="fireflyStyle()"
          ></div>
        </div>
        <div v-if="sweetness >= 21" :class="['star-particles', sweetnessLevelClass]">
          <div
            v-for="n in starParticleCount"
            :key="`star-${n}`"
            class="star-particle"
            :style="starParticleStyle()"
          >✨</div>
        </div>
      </div>

      <!-- 爱心值特效 -->
      <div v-if="love >= 5" class="love-effects">
        <div
          class="love-aura"
          :style="{ transform: `translate(-50%, -50%) scale(${loveAuraScale})` }"
        >
          <div v-if="love >= 80" class="heart-core">💖</div>
          <div class="love-ring"></div>
          <div v-if="love >= 40" class="heart-particles">
            <div
              v-for="n in heartParticleCount"
              :key="`heart-${n}`"
              class="heart-particle"
              :style="heartParticleStyle()"
            >💕</div>
          </div>
        </div>
      </div>
    </div>

    <div :class="['tree-main', stageClass]">
      <div class="ground"></div>

      <!-- Lv1 种子 -->
      <div v-if="level === 1" class="seedling">
        <div class="seedling-stem"></div>
        <div class="seedling-leaves">
          <div class="seedling-leaf">🌱</div>
          <div class="seedling-leaf">🌱</div>
        </div>
      </div>

      <!-- Lv2+ 圣诞树结构 -->
      <div v-if="level >= 2" class="tree-structure">
        <div v-if="level >= 2" class="tree-roots">
          <div class="root root-1"></div>
          <div class="root root-2"></div>
          <div class="root root-3"></div>
        </div>
        <div v-if="level >= 2" class="christmas-tree">
          <div v-if="level >= 5" class="tree-star">⭐</div>
          <div class="tree-layer layer-1">
            <div class="tree-section"></div>
            <div v-if="level >= 3" class="tree-lights">
              <div class="light light-red" style="left: 30%; top: 40%"></div>
              <div class="light light-gold" style="right: 30%; top: 60%"></div>
            </div>
          </div>
          <div v-if="level >= 3" class="tree-layer layer-2">
            <div class="tree-section"></div>
            <div class="tree-lights">
              <div class="light light-gold" style="left: 20%; top: 25%"></div>
              <div class="light light-red" style="right: 25%; top: 45%"></div>
              <div class="light light-gold" style="left: 50%; top: 65%"></div>
            </div>
          </div>
          <div v-if="level >= 4" class="tree-layer layer-3">
            <div class="tree-section"></div>
            <div class="tree-lights">
              <div class="light light-red" style="left: 15%; top: 20%"></div>
              <div class="light light-gold" style="right: 20%; top: 35%"></div>
              <div class="light light-red" style="left: 45%; top: 55%"></div>
              <div class="light light-gold" style="right: 40%; top: 70%"></div>
            </div>
          </div>
          <div v-if="level >= 5" class="tree-layer layer-4">
            <div class="tree-section"></div>
            <div class="tree-lights">
              <div class="light light-gold" style="left: 10%; top: 15%"></div>
              <div class="light light-red" style="right: 15%; top: 30%"></div>
              <div class="light light-gold" style="left: 40%; top: 50%"></div>
              <div class="light light-red" style="right: 35%; top: 65%"></div>
              <div class="light light-gold" style="left: 65%; top: 80%"></div>
            </div>
          </div>
        </div>
        <div v-if="level >= 4" class="tree-flowers">
          <div class="flower" style="left: 25%; top: 30%">🌸</div>
          <div class="flower" style="right: 30%; top: 45%">🌺</div>
          <div class="flower" style="left: 60%; top: 65%">🌸</div>
          <div v-if="level >= 5" class="flower" style="right: 20%; top: 80%">🌺</div>
        </div>
        <div v-if="level >= 5" class="tree-fruits">
          <div class="fruit" style="left: 35%; top: 25%">🔴</div>
          <div class="fruit" style="right: 40%; top: 40%">🟡</div>
          <div class="fruit" style="left: 20%; top: 60%">🔴</div>
          <div class="fruit" style="right: 25%; top: 75%">🟡</div>
        </div>
        <div class="tree-trunk">
          <div class="trunk-texture"></div>
        </div>
      </div>
    </div>

    <div :class="['health-indicator', healthClass]">
      <div class="health-glow"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  level: { type: Number, default: 1 },
  health: { type: Number, default: 10 },
  care: { type: Number, default: 0 },
  companion: { type: Number, default: 0 },
  love: { type: Number, default: 0 },
  sweetness: { type: Number, default: 0 }
})

const stageClass = computed(() => `stage-level-${props.level}`)

const healthClass = computed(() =>
  props.health < 20 ? 'health-sick' : props.health < 40 ? 'health-poor' : 'health-good'
)

const careLevelClass = computed(() =>
  props.care >= 91
    ? 'effect-level-5'
    : props.care >= 61
      ? 'effect-level-4'
      : props.care >= 41
        ? 'effect-level-3'
        : props.care >= 21
          ? 'effect-level-2'
          : 'effect-level-1'
)

const companionLevelClass = computed(() =>
  props.companion >= 91
    ? 'effect-level-5'
    : props.companion >= 61
      ? 'effect-level-4'
      : props.companion >= 41
        ? 'effect-level-3'
        : props.companion >= 21
          ? 'effect-level-2'
          : 'effect-level-1'
)

const sweetnessLevelClass = computed(() =>
  props.sweetness >= 91
    ? 'effect-level-5'
    : props.sweetness >= 61
      ? 'effect-level-4'
      : props.sweetness >= 41
        ? 'effect-level-3'
        : props.sweetness >= 21
          ? 'effect-level-2'
          : 'effect-level-1'
)

const loveLevelClass = computed(() =>
  props.love >= 91
    ? 'effect-level-5'
    : props.love >= 61
      ? 'effect-level-4'
      : props.love >= 41
        ? 'effect-level-3'
        : props.love >= 21
          ? 'effect-level-2'
          : 'effect-level-1'
)

const lifeParticleCount = computed(() =>
  props.care >= 91
    ? Math.min(16, 14 + Math.floor((props.care - 91) / 5))
    : props.care >= 61
      ? Math.min(14, 12 + Math.floor((props.care - 61) / 15))
      : props.care >= 41
        ? Math.min(12, 10 + Math.floor((props.care - 41) / 10))
        : props.care >= 21
          ? Math.min(10, 8 + Math.floor((props.care - 21) / 10))
          : props.care >= 5
            ? Math.min(8, 6 + Math.floor((props.care - 5) / 8))
            : 6
)

const petalCount = computed(() =>
  props.care >= 91
    ? Math.min(15, 12 + Math.floor((props.care - 91) / 4))
    : props.care >= 61
      ? Math.min(12, 9 + Math.floor((props.care - 61) / 10))
      : props.care >= 41
        ? Math.min(9, 6 + Math.floor((props.care - 41) / 7))
        : props.care >= 21
          ? Math.min(6, 4 + Math.floor((props.care - 21) / 10))
          : 4
)

const butterflyCount = computed(() =>
  props.companion >= 91
    ? Math.min(15, 12 + Math.floor((props.companion - 91) / 3))
    : props.companion >= 61
      ? Math.min(12, 9 + Math.floor((props.companion - 61) / 10))
      : props.companion >= 41
        ? Math.min(9, 6 + Math.floor((props.companion - 41) / 7))
        : props.companion >= 21
          ? Math.min(6, 4 + Math.floor((props.companion - 21) / 10))
          : props.companion >= 5
            ? Math.min(4, 2 + Math.floor((props.companion - 5) / 8))
            : 2
)

const fireflyCount = computed(() =>
  props.sweetness >= 91
    ? Math.min(10, 8 + Math.floor((props.sweetness - 91) / 5))
    : props.sweetness >= 61
      ? Math.min(8, 6 + Math.floor((props.sweetness - 61) / 15))
      : props.sweetness >= 41
        ? Math.min(6, 4 + Math.floor((props.sweetness - 41) / 10))
        : props.sweetness >= 21
          ? Math.min(4, 3 + Math.floor((props.sweetness - 21) / 10))
          : props.sweetness >= 5
            ? Math.min(3, 2 + Math.floor((props.sweetness - 5) / 8))
            : 2
)

const starParticleCount = computed(() =>
  props.sweetness >= 91
    ? Math.min(15, 12 + Math.floor((props.sweetness - 91) / 3))
    : props.sweetness >= 61
      ? Math.min(12, 9 + Math.floor((props.sweetness - 61) / 10))
      : props.sweetness >= 41
        ? Math.min(9, 6 + Math.floor((props.sweetness - 41) / 7))
        : props.sweetness >= 21
          ? Math.min(6, 3 + Math.floor((props.sweetness - 21) / 7))
          : 0
)

const heartParticleCount = computed(() =>
  props.love >= 91
    ? Math.min(12, 9 + Math.floor((props.love - 91) / 3))
    : props.love >= 61
      ? Math.min(9, 7 + Math.floor((props.love - 61) / 15))
      : props.love >= 41
        ? Math.min(7, 5 + Math.floor((props.love - 41) / 10))
        : props.love >= 21
          ? Math.min(5, 3 + Math.floor((props.love - 21) / 10))
          : 0
)

const petalStyle = () => ({
  left: Math.random() * 100 + '%',
  animationDelay: Math.random() * 5 + 's',
  animationDuration: 3 + Math.random() * 2 + 's'
})

const butterflyStyle = () => ({
  left: Math.random() * 100 + '%',
  top: Math.random() * 100 + '%',
  animationDelay: Math.random() * 3 + 's',
  animationDuration: 4 + Math.random() * 2 + 's'
})

const fireflyStyle = () => ({
  left: Math.random() * 100 + '%',
  top: Math.random() * 100 + '%',
  animationDelay: Math.random() * 4 + 's',
  animationDuration: 5 + Math.random() * 3 + 's'
})

const starParticleStyle = () => ({
  left: Math.random() * 100 + '%',
  top: Math.random() * 100 + '%',
  animationDelay: Math.random() * 2 + 's'
})

const heartParticleStyle = () => ({
  left: Math.random() * 100 + '%',
  animationDelay: Math.random() * 3 + 's',
  animationDuration: 2 + Math.random() * 1 + 's'
})

const loveAuraScale = computed(() => {
  if (props.love >= 5 && props.love < 21) return 1 + (props.love - 5) * 0.01
  if (props.love >= 21 && props.love < 41) return 1.15 + (props.love - 21) * 0.005
  if (props.love >= 41 && props.love < 61) return 1.25 + (props.love - 41) * 0.005
  if (props.love >= 61 && props.love < 81) return 1.35 + (props.love - 61) * 0.005
  if (props.love >= 81 && props.love < 91) return 1.45 + (props.love - 81) * 0.008
  if (props.love >= 91) return 1.52 + (props.love - 91) * 0.009
  return 1
})

const shieldScale = computed(() => {
  if (props.companion >= 21 && props.companion < 41) return 0.8 + (props.companion - 21) * 0.01
  if (props.companion >= 41 && props.companion < 61) return 1 + (props.companion - 41) * 0.0075
  if (props.companion >= 61 && props.companion < 81) return 1.15 + (props.companion - 61) * 0.005
  if (props.companion >= 81 && props.companion < 91) return 1.25 + (props.companion - 81) * 0.008
  if (props.companion >= 91) return 1.32 + (props.companion - 91) * 0.009
  return 0.8
})
</script>

<style scoped>
.love-tree-container {
  position: relative;
  width: 100%;
  height: 400px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.effects-layer {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
}
.tree-main {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  transition: all 0.5s ease;
}
.tree-trunk {
  width: 20px;
  height: 80px;
  background: linear-gradient(to bottom, #8b4513, #654321);
  border-radius: 10px;
  position: relative;
}
.tree-crown {
  position: relative;
  margin-top: -10px;
}
.ground {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 30px;
  background: linear-gradient(to bottom, rgba(34, 139, 34, 0.6), rgba(107, 142, 35, 0.7) 30%, rgba(139, 69, 19, 0.8));
  border-radius: 0 0 15px 15px;
}
.seedling {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 60px;
}
.seedling-stem {
  width: 4px;
  height: 35px;
  background: linear-gradient(to bottom, #90ee90, #228b22);
  border-radius: 2px;
  position: relative;
}
.seedling-leaves {
  position: absolute;
  top: -5px;
  left: 50%;
  transform: translate(-50%);
}
.seedling-leaf {
  position: absolute;
  font-size: 14px;
  animation: leafSway 3s ease-in-out infinite;
}
.seedling-leaf:nth-child(1) { left: -15px; top: 0; animation-delay: 0s; }
.seedling-leaf:nth-child(2) { right: -15px; top: 0; animation-delay: 1s; }
.tree-structure {
  position: absolute;
  bottom: 30px;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 200px;
  height: 200px;
}
.tree-roots {
  position: absolute;
  bottom: -10px;
  left: 50%;
  transform: translate(-50%);
  width: 100px;
  height: 20px;
}
.root {
  position: absolute;
  background: rgba(139, 69, 19, 0.6);
  border-radius: 2px;
}
.root-1 {
  width: 30px;
  height: 3px;
  left: 10px;
  bottom: 0;
  transform: rotate(-20deg);
}
.root-2 {
  width: 25px;
  height: 3px;
  right: 10px;
  bottom: 0;
  transform: rotate(20deg);
}
.root-3 {
  width: 20px;
  height: 2px;
  left: 50%;
  bottom: 5px;
  transform: translate(-50%);
}
.tree-trunk {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translate(-50%);
  background: linear-gradient(to right, #8b4513, sienna, #8b4513);
  border-radius: 8px 8px 4px 4px;
  box-shadow: inset 2px 0 4px rgba(0, 0, 0, 0.3);
  z-index: 1;
}
.trunk-texture {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    90deg,
    transparent,
    transparent 2px,
    rgba(101, 67, 33, 0.3) 2px,
    rgba(101, 67, 33, 0.3) 3px
  );
  border-radius: inherit;
}
.stage-level-2 .tree-trunk { width: 12px; height: 60px; }
.stage-level-3 .tree-trunk { width: 16px; height: 80px; }
.stage-level-4 .tree-trunk { width: 20px; height: 100px; }
.stage-level-5 .tree-trunk { width: 25px; height: 120px; }
.christmas-tree {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translate(-50%);
  z-index: 2;
}
.tree-star {
  position: absolute;
  top: -25px;
  left: 50%;
  transform: translate(-50%);
  font-size: 20px;
  z-index: 10;
  animation: starTwinkle 2s ease-in-out infinite alternate;
  filter: drop-shadow(0 0 8px #ffd700);
}
@keyframes starTwinkle {
  0% { opacity: 0.8; transform: translate(-50%) scale(1); }
  100% { opacity: 1; transform: translate(-50%) scale(1.1); }
}
.tree-layer { position: relative; margin: -8px auto; }
.tree-section {
  width: 0;
  height: 0;
  margin: 0 auto;
  position: relative;
  filter: drop-shadow(2px 2px 4px rgba(0, 0, 0, 0.3));
}
.layer-1 .tree-section {
  border-left: 25px solid transparent;
  border-right: 25px solid transparent;
  border-bottom: 35px solid #0d5016;
}
.layer-2 .tree-section {
  border-left: 40px solid transparent;
  border-right: 40px solid transparent;
  border-bottom: 45px solid #0f5c1a;
}
.layer-3 .tree-section {
  border-left: 55px solid transparent;
  border-right: 55px solid transparent;
  border-bottom: 55px solid #11681e;
}
.layer-4 .tree-section {
  border-left: 70px solid transparent;
  border-right: 70px solid transparent;
  border-bottom: 65px solid #137422;
}
.tree-lights {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.light {
  position: absolute;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  animation: lightTwinkle 1.5s ease-in-out infinite alternate;
}
.light-red {
  background: radial-gradient(circle, #ff4444, #cc0000);
  box-shadow: 0 0 8px #ff4444, 0 0 12px #ff4444;
}
.light-gold {
  background: radial-gradient(circle, gold, #ffaa00);
  box-shadow: 0 0 8px gold, 0 0 12px gold;
}
@keyframes lightTwinkle {
  0% { opacity: 0.6; transform: scale(0.8); }
  100% { opacity: 1; transform: scale(1.2); }
}
.tree-flowers {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translate(-50%);
  width: 150px;
  height: 200px;
  pointer-events: none;
}
.flower {
  position: absolute;
  font-size: 16px;
  animation: ornamentTwinkle 2.5s ease-in-out infinite;
  filter: drop-shadow(0 0 4px rgba(255, 182, 193, 0.8));
}
.tree-fruits {
  position: absolute;
  bottom: 60px;
  left: 50%;
  transform: translate(-50%);
  width: 150px;
  height: 200px;
  pointer-events: none;
}
.fruit {
  position: absolute;
  font-size: 18px;
  animation: ornamentSway 3s ease-in-out infinite;
  filter: drop-shadow(0 0 6px rgba(255, 0, 0, 0.6));
}
@keyframes ornamentTwinkle {
  0%, 100% { transform: scale(1) rotate(-3deg); opacity: 0.8; }
  50% { transform: scale(1.15) rotate(3deg); opacity: 1; }
}
@keyframes ornamentSway {
  0%, 100% { transform: scale(1) rotate(-2deg); opacity: 0.9; }
  50% { transform: scale(1.1) rotate(2deg); opacity: 1; }
}
@keyframes leafSway {
  0%, 100% { transform: rotate(-10deg); }
  50% { transform: rotate(10deg); }
}
.health-indicator {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translate(-50%);
  width: 60px;
  height: 60px;
  border-radius: 50%;
  z-index: 0;
}
.health-glow {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  animation: healthPulse 2s ease-in-out infinite;
}
.health-sick .health-glow {
  background: radial-gradient(circle, rgba(255, 107, 107, 0.3), transparent);
}
.health-poor .health-glow {
  background: radial-gradient(circle, rgba(255, 193, 7, 0.3), transparent);
}
.health-good .health-glow {
  background: radial-gradient(circle, rgba(40, 167, 69, 0.3), transparent);
}
.life-particles {
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translate(-50%);
  width: 100px;
  height: 200px;
}
.life-particle {
  position: absolute;
  width: 4px;
  height: 4px;
  background: #90ee90;
  border-radius: 50%;
  bottom: 0;
  left: 50%;
  animation: lifeRise 3s ease-out infinite;
  box-shadow: 0 0 6px #90ee90;
  transition: all 0.3s ease;
}
.effect-level-1 .life-particle { opacity: 0.6; box-shadow: 0 0 4px #90ee90; }
.effect-level-2 .life-particle { opacity: 0.7; box-shadow: 0 0 6px #90ee90; }
.effect-level-3 .life-particle { opacity: 0.8; box-shadow: 0 0 8px #90ee90; }
.effect-level-4 .life-particle { opacity: 0.9; box-shadow: 0 0 10px #90ee90; }
.effect-level-5 .life-particle { opacity: 1; box-shadow: 0 0 12px #90ee90, 0 0 20px #90ee90; }
.life-particle:nth-child(2n) { animation-delay: 0.5s; left: 45%; }
.life-particle:nth-child(3n) { animation-delay: 1s; left: 55%; }
.falling-petals {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.petal {
  position: absolute;
  width: 8px;
  height: 8px;
  background: #ffb6c1;
  border-radius: 50% 0;
  top: -10px;
  animation: petalFall linear infinite;
  transform: rotate(45deg);
}
.effect-level-3 .petal,
.effect-level-4 .petal,
.effect-level-5 .petal {
  background: #ff69b4;
}
.effect-level-5 .petal {
  background: linear-gradient(45deg, #ff69b4, #fff);
}
.butterflies {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.butterfly {
  position: absolute;
  font-size: 16px;
  animation: butterflyFly ease-in-out infinite;
  filter: hue-rotate(0deg);
  transition: all 0.3s ease;
}
.effect-level-1 .butterfly { font-size: 14px; filter: hue-rotate(0deg); opacity: 0.7; }
.effect-level-2 .butterfly { font-size: 15px; filter: hue-rotate(200deg); opacity: 0.8; }
.effect-level-3 .butterfly { font-size: 16px; filter: hue-rotate(60deg); opacity: 0.9; }
.effect-level-4 .butterfly { font-size: 17px; filter: hue-rotate(300deg); opacity: 0.95; }
.effect-level-5 .butterfly {
  font-size: 18px;
  filter: hue-rotate(300deg) drop-shadow(0 0 4px rgba(255, 255, 255, 0.5));
  opacity: 1;
}
.guardian-shield {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 120px;
  height: 120px;
  border: 2px solid rgba(135, 206, 250, 0.8);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(135, 206, 250, 0.1), transparent);
  z-index: 8;
  animation: guardianPulse 2s ease-in-out infinite;
}
.guardian-shield:before {
  content: '';
  position: absolute;
  inset: -3px;
  border: 1px solid transparent;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    rgba(135, 206, 250, 0) 0deg,
    rgba(135, 206, 250, 0.8) 40deg,
    rgba(135, 206, 250, 0) 80deg,
    rgba(135, 206, 250, 0.6) 120deg,
    rgba(135, 206, 250, 0) 160deg,
    rgba(135, 206, 250, 0.8) 200deg,
    rgba(135, 206, 250, 0) 240deg,
    rgba(135, 206, 250, 0.4) 280deg,
    rgba(135, 206, 250, 0) 360deg
  );
  animation: sparkleRotate 3s linear infinite;
}
.guardian-shield:after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 4px;
  height: 4px;
  background: #87ceeb;
  border-radius: 50%;
  box-shadow: 0 0 8px #87ceeb, 0 0 16px #87ceeb, 0 0 24px #87ceeb;
  animation: guardianSparkle 1.5s ease-in-out infinite;
}
.effect-level-4 .guardian-shield,
.effect-level-5 .guardian-shield {
  border-color: #87cefa;
  box-shadow: 0 0 15px rgba(135, 206, 250, 0.6);
}
.effect-level-5 .guardian-shield {
  box-shadow: 0 0 20px rgba(135, 206, 250, 0.8), 0 0 30px rgba(135, 206, 250, 0.4);
}
.effect-level-5 .guardian-shield:after {
  box-shadow: 0 0 12px #87ceeb, 0 0 24px #87ceeb, 0 0 36px #87ceeb, 0 0 48px #87ceeb;
}
.fireflies {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.firefly {
  position: absolute;
  width: 4px;
  height: 4px;
  background: gold;
  border-radius: 50%;
  animation: fireflyGlow ease-in-out infinite;
  box-shadow: 0 0 12px gold, 0 0 18px gold;
  transition: all 0.3s ease;
}
.effect-level-1 .firefly {
  width: 3px;
  height: 3px;
  box-shadow: 0 0 8px gold, 0 0 12px gold;
  opacity: 0.7;
}
.effect-level-2 .firefly,
.effect-level-3 .firefly,
.effect-level-4 .firefly,
.effect-level-5 .firefly {
  animation: fireflyTrail ease-in-out infinite;
}
.effect-level-2 .firefly {
  width: 4px;
  height: 4px;
  box-shadow: 0 0 10px gold, 0 0 15px gold;
  opacity: 0.8;
}
.effect-level-3 .firefly {
  width: 4px;
  height: 4px;
  box-shadow: 0 0 12px gold, 0 0 18px gold;
  opacity: 0.9;
}
.effect-level-4 .firefly {
  width: 5px;
  height: 5px;
  box-shadow: 0 0 15px gold, 0 0 25px gold, 0 0 35px gold;
  opacity: 0.95;
}
.effect-level-5 .firefly {
  width: 6px;
  height: 6px;
  box-shadow: 0 0 20px gold, 0 0 30px gold, 0 0 45px gold;
  opacity: 1;
}
.star-particles {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.star-particle {
  position: absolute;
  font-size: 12px;
  animation: starTwinkle 2s ease-in-out infinite;
}
.love-aura {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 180px;
  height: 180px;
  z-index: 10;
}
.heart-core {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 24px;
  animation: heartBeat 1.5s ease-in-out infinite;
}
.love-ring {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  width: 140px;
  height: 140px;
  border: 3px solid rgba(255, 105, 180, 0.7);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 105, 180, 0.15), transparent);
  box-shadow: 0 0 15px rgba(255, 105, 180, 0.5);
}
.heart-particles {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
}
.heart-particle {
  position: absolute;
  font-size: 10px;
  bottom: 0;
  animation: heartRise linear infinite;
}
@keyframes healthPulse {
  0%, 100% { opacity: 0.5; transform: translate(-50%) scale(1); }
  50% { opacity: 0.8; transform: translate(-50%) scale(1.1); }
}
@keyframes lifeRise {
  0% { opacity: 1; transform: translateY(0) scale(1); }
  100% { opacity: 0; transform: translateY(-200px) scale(0.5); }
}
@keyframes petalFall {
  0% { opacity: 1; transform: translateY(-10px) rotate(45deg); }
  100% { opacity: 0; transform: translateY(400px) rotate(405deg); }
}
@keyframes butterflyFly {
  0% { transform: translate(0) rotate(0); }
  25% { transform: translate(20px, -10px) rotate(5deg); }
  50% { transform: translate(-10px, -20px) rotate(-5deg); }
  75% { transform: translate(-20px, 10px) rotate(3deg); }
  100% { transform: translate(0) rotate(0); }
}
@keyframes shieldPulse {
  0%, 100% { transform: translate(-50%, -50%) scale(1); opacity: 0.5; }
  50% { transform: translate(-50%, -50%) scale(1.05); opacity: 0.8; }
}
@keyframes fireflyGlow {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.3); }
}
@keyframes fireflyTrail {
  0% { opacity: 0.4; transform: scale(1) translate(0) translateY(0); box-shadow: 0 0 8px gold; }
  25% { opacity: 0.8; transform: scale(1.2) translate(10px) translateY(-5px); box-shadow: 0 0 15px gold, 0 0 25px gold; }
  50% { opacity: 1; transform: scale(1.3) translate(-5px) translateY(-10px); box-shadow: 0 0 20px gold, 0 0 30px gold; }
  75% { opacity: 0.8; transform: scale(1.1) translate(-10px) translateY(5px); box-shadow: 0 0 15px gold, 0 0 25px gold; }
  100% { opacity: 0.4; transform: scale(1) translate(0) translateY(0); box-shadow: 0 0 8px gold; }
}
@keyframes starTwinkle {
  0%, 100% { opacity: 0.5; transform: scale(1) rotate(0); }
  50% { opacity: 1; transform: scale(1.3) rotate(180deg); }
}
@keyframes heartBeat {
  0%, 100% { transform: translate(-50%, -50%) scale(1); }
  50% { transform: translate(-50%, -50%) scale(1.2); }
}
@keyframes heartRise {
  0% { opacity: 1; transform: translateY(0) scale(1); }
  100% { opacity: 0; transform: translateY(-150px) scale(0.5); }
}
.tree-buds { position: absolute; inset: 0; }
.bud {
  position: absolute;
  width: 8px;
  height: 8px;
  background: #6b8e23;
  border-radius: 50%;
  box-shadow: 0 0 2px #6b8e23;
}
.bud:nth-child(1) { top: 30%; left: 35%; }
.bud:nth-child(2) { top: 50%; right: 20%; }
.bud:nth-child(3) { bottom: 25%; left: 45%; }
@keyframes guardianPulse {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 0.8; }
}
@keyframes sparkleRotate {
  0% { transform: rotate(0); }
  100% { transform: rotate(360deg); }
}
@keyframes guardianSparkle {
  0%, 100% { opacity: 0.5; }
  50% { opacity: 1; }
}
@media (max-width: 768px) {
  .love-tree-container {
    height: 280px;
    max-width: 100%;
    width: 100%;
  }
  .tree-main { transform: scale(0.85); }
  .seedling {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) scale(0.85);
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 60px;
  }
  .stage-seedling .tree-trunk { width: 12px; height: 50px; }
  .stage-seedling .tree-crown { width: 40px; height: 40px; }
  .stage-growing .tree-trunk { width: 16px; height: 70px; }
  .stage-growing .tree-crown { width: 80px; height: 80px; }
  .stage-mature .tree-trunk { width: 20px; height: 90px; }
  .stage-mature .tree-crown { width: 110px; height: 110px; }
  .health-indicator {
    width: 45px;
    height: 45px;
    bottom: 8px;
  }
  .guardian-shield {
    width: 100px;
    height: 100px;
  }
  .love-aura {
    width: 140px;
    height: 140px;
  }
  .love-ring {
    width: 100px;
    height: 100px;
  }
  .life-particles {
    width: 100px;
    height: 180px;
  }
  .life-particle {
    width: 4px;
    height: 4px;
  }
  .petal { width: 8px; height: 8px; }
  .butterfly { font-size: 14px; }
  .firefly { width: 3px; height: 3px; }
  .star-particle { font-size: 12px; }
  .heart-particle { font-size: 10px; }
}
</style>
