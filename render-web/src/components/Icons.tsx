import {
  ArrowLeftRight, Baby, Banknote, Bot, Briefcase, Building, Car, ChartLine, Clock, Coins, Cpu, Droplets, Earth,
  Factory, Flame, Fuel, Gauge, Globe, GraduationCap, HeartPulse, Hospital, Hourglass, House, Landmark, Leaf,
  Lightbulb, LucideIcon, MapPin, MessageCircle, Network, Package, Percent, PersonStanding, Plane, Rocket, Scale,
  Ship, ShoppingCart, Smartphone, Sprout, Store, Sun, Target, Thermometer, TrainFront, Trees, TrendingDown,
  TrendingUp, UserRound, Users, Video, Wallet, Wheat, Wifi, Zap,
} from "lucide-react";

// Tên icon (Python chọn theo từ khoá trong câu, src/render/web.py ICON_KEYWORDS) -> component.
// Icon của lucide (giấy phép ISC). Tên lạ thì không vẽ icon.
export const ICONS: Record<string, LucideIcon> = {
  "arrow-left-right": ArrowLeftRight, baby: Baby, banknote: Banknote, bot: Bot, briefcase: Briefcase,
  building: Building, car: Car, "chart-line": ChartLine, clock: Clock, coins: Coins, cpu: Cpu, droplets: Droplets,
  earth: Earth, factory: Factory, flame: Flame, fuel: Fuel, gauge: Gauge, globe: Globe, "graduation-cap": GraduationCap,
  "heart-pulse": HeartPulse, hospital: Hospital, hourglass: Hourglass, house: House, landmark: Landmark, leaf: Leaf,
  lightbulb: Lightbulb, "map-pin": MapPin, message: MessageCircle, network: Network, package: Package,
  percent: Percent, person: PersonStanding, plane: Plane, rocket: Rocket, scale: Scale, ship: Ship,
  "shopping-cart": ShoppingCart, smartphone: Smartphone, sprout: Sprout, store: Store, sun: Sun, target: Target,
  thermometer: Thermometer, train: TrainFront, trees: Trees, "trending-down": TrendingDown, "trending-up": TrendingUp,
  user: UserRound, users: Users, video: Video, wallet: Wallet, wheat: Wheat, wifi: Wifi, zap: Zap,
};
