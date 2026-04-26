class ProjectsPage { 
  visit() { 
    cy.visit('/projects'); 
  } 
  getProjectThumbnails() { 
    return cy.get('h3'); 
  } 
} 
module.exports = new ProjectsPage();