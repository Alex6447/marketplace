import { useRoute } from "@/lib/router";
import { ProductView } from "@/views/ProductView";
import { ProjectView } from "@/views/ProjectView";
import { ProjectsView } from "@/views/ProjectsView";

// Дашборд менеджера: проект → товар → идеи (стадия [2]) → концепции (стадия [3]).
// Маршрутизация — на хэше (см. lib/router.ts), каждый экран сам рисует AppShell.
function App() {
  const route = useRoute();

  switch (route.name) {
    case "project":
      return <ProjectView projectId={route.id} />;
    case "product":
      return <ProductView productId={route.id} />;
    default:
      return <ProjectsView />;
  }
}

export default App;
